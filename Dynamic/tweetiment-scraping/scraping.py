#This file performs the following functions (scraping data basically):
#1. Extracts streaming data from Twitter using Tweepy with Twitter API v2
#2. Pre-processes the data
#3. Loads it into a MySQL database

import credentials #Import the keys from credentials.py
import settings #Import the related setting constants from settings.py 

import os
import psycopg2
import re
import tweepy
import mysql.connector
import pandas as pd
from textblob import TextBlob
from dateutil import parser #for converting ISO 8601 date into the correct format
import json #to convert the decoded raw tweet data string to a dictionary

#Override the tweepy.StreamingClient class to add logic to on_data
class MyStream(tweepy.StreamingClient):
    #This is called when raw data is received from the stream. This method handles sending the 
    #data to other methods.
    def on_data(self, raw_data):
        '''
        Extract info from tweets
        ''' 
        #decoding the raw data which is in the form of a byte object we get a string of a dict,
        #we then convert the string to an actual dict and store it in data
        data = json.loads(raw_data.decode('utf-8'))
        #Extract the attributes from each tweet
        tweet_id = data['data']['id'] #Tweet ID
        created_at = parser.parse(data['data']['created_at']).strftime("%Y-%m-%d %H:%M:%S") #Creation time of the Tweet
        text = remove_emojis(data['data']['text']) #Content of the tweet, pre-processing it  
        text = clean_tweet_text(text)
        retweet_count = data['data']['public_metrics']['retweet_count']
        like_count = data['data']['public_metrics']['like_count']
        longitude = None
        latitude = None
        if 'coordinates' in data['data']['geo']:
            longitude = data['data']['geo']['coordinates']['coordinates'][0]
            latitude = data['data']['geo']['coordinates']['coordinates'][1]
        sentiment = TextBlob(text).sentiment #Retrieving the sentiment of the tweet
        polarity = sentiment.polarity #Retrieving the polarity of the tweet
        subjectivity = sentiment.subjectivity #Retrieving the sentiment of the tweet
        
        #Extracting user info
        user_created_at = parser.parse(data['includes']['users'][0]['created_at']).strftime("%Y-%m-%d %H:%M:%S")
        user_location = None
        if 'location' in data['includes']['users'][0]:
            user_location = remove_emojis(data['includes']['users'][0]['location'])
        user_description = remove_emojis(data['includes']['users'][0]['description'])
        user_followers_count = data['includes']['users'][0]['public_metrics']['followers_count']
        
        #print(data['data']['text'])
        #print(f'Longitude: {longitude}, Latitude: {latitude}')
        
        #Storing all the data in Heroku PostgreSQL
        cursor = connection.cursor()
        query = f"INSERT INTO {settings.TABLE_NAME} (tweet_id, created_at, text, polarity, subjectivity, user_created_at, user_location, user_description, user_followers_count, longitude, latitude, retweet_count, like_count) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        values = (tweet_id, created_at, text, polarity, subjectivity, user_created_at, user_location, user_description, user_followers_count, longitude, latitude, retweet_count, like_count)
        cursor.execute(query, values)
        connection.commit()
        
        delete_query = f"DELETE FROM {settings.TABLE_NAME} WHERE tweet_id IN (SELECT tweet_id FROM {settings.TABLE_NAME} ORDER BY created_at asc LIMIT 200) AND (SELECT COUNT(*) FROM Facebook) > 9600;"
        cursor.execute(delete_query)
        connection.commit()
        cursor.close()
        
#     #This is called when includes are received.
#     def on_includes(self, includes):
#         pass
        
#      #This is called when a Tweet is received.
#     def on_tweet(self, tweet):
#         pass
        
    def on_errors(self, status_code):
        '''
        Since the Twitter API has rate limits, we must stop scraping data once the limit 
        has been crossed.
        '''
        if status_code == 420: #marks the end of the monthly limit rate (2M)
            #return False to disconnect the stream
            return False
        
#Functions used to pre-process the tweet text
def clean_tweet_text(tweet_text): 
    ''' 
    Removing links and special characters using Regex
    '''
    return ' '.join(re.sub("(@[A-Za-z0-9]+)|([^0-9A-Za-z \t])|(\w+:\/\/\S+)", " ", tweet_text).split()) 
def remove_emojis(tweet_text):
    '''
    Strip all non-ASCII characters so that emojis are removed
    '''
    if tweet_text:
        return tweet_text.encode('ascii', 'ignore').decode('ascii')
    else:
        return None

DATABASE_URL = os.environ['DATABASE_URL']

connection = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = connection.cursor()

'''
Check if tables exist. If not, then create new ones.
'''
#Table 1
cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = '{0}'
        """.format(settings.TABLE_NAME))
if cursor.fetchone()[0] == 0:
    cursor.execute("CREATE TABLE {} ({});".format(settings.TABLE_NAME, settings.TABLE_ATTRIBUTES))
    connection.commit()
#Table 2
cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = '{0}'
        """.format(settings.TABLE_NAME_1))
if cursor.fetchone()[0] == 0:
    cursor.execute("CREATE TABLE {} ({});".format(settings.TABLE_NAME_1, settings.TABLE_ATTRIBUTES_1))
    query = f"INSERT INTO {settings.TABLE_NAME_1} (daily_tweets_num, impressions) VALUES (0, 0)"
    cursor.execute(query)
    connection.commit()
cursor.close()

#Authentication
client = tweepy.Client(credentials.BEARER_TOKEN)

#Streaming tweets
myStream = MyStream(credentials.BEARER_TOKEN)
#For filtering twitter tweets we need to set up rules so that tweets are streamed accordingly 
#Deleting any previous rules if they exist
if myStream.get_rules()[0]:
    myStream.delete_rules([rule.id for rule in myStream.get_rules()[0]])
#Adding a new rule
myStream.add_rules(tweepy.StreamRule(f"{settings.TRACK_WORDS} lang:en -is:retweet"))
#Filtering the tweets using the rule added and using expansions to gather non-default tweet data
myStream.filter(expansions=['author_id'], 
                user_fields=['created_at','location','description','public_metrics'],
                tweet_fields=['created_at','geo','public_metrics'])
#The following part won't be reached as the streaming client won't stop automatically 
#We need to STOP it manually
#Closing the database
connection.close()