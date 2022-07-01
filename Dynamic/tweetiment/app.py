#Code for all that happens in the frontend of the Web Application
import pandas as pd
import re
import nltk
nltk.download('punkt')
nltk.download('stopwords')
from nltk.probability import FreqDist
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from textblob import TextBlob

import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output

import plotly.graph_objs as go
import settings
import itertools
import math
import base64
from flask import Flask
import os
import psycopg2
import datetime
 
#Dash default CSS sheet
external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']

app = dash.Dash(__name__, external_stylesheets=external_stylesheets)
app.title = 'Tweetiment'

server = app.server

#Dash layout
#The core framework of Dash web app is using app.layout as a background layout

#1. html.Div(id='live-update-graph') describes the top part of the dashboard in the application, including descriptions for tweet number and potential impressions.
#2. html.Div(id='live-update-graph-bottom') describes the bottom part of the dashboard in the web app.
#3. dcc.Interval is the key to allow the application to update information regularly, i.e. timer for updating data every 10 seconds
app.layout = html.Div(children=[html.H2('Twitter Sentiment Analysis', style={'textAlign': 'center'}),
                                html.H4('(Last App update: July 1, 2022)', style={'textAlign': 'right'}),
                                html.Div(id='live-update-graph'),
                                html.Div(id='live-update-graph-bottom'),
                                html.Div(className='row', 
                                         children=[dcc.Markdown("__Tracking sentiments to see how the world is feeling!__"),], style={'width': '35%', 'marginLeft': 70}),
                                html.Br(),
                                html.Div(className='row', 
                                         children=[html.Div(className='three columns',
                                                            children=[html.P('The data for the analysis being shown is being extracted from the:'),
                                                                      html.A('Twitter API', href='https://developer.twitter.com')]),
                                                   html.Div(className='three columns',
                                                            children=[html.P('The code for this Web Application can be found at:'),
                                                                      html.A('GitHub', href='https://github.com/mrigank-sondhi/twitter-sentiment-analysis')]),
                                                   html.Div(className='three columns',
                                                            children=[html.P('This visualization has been made with:'),
                                                                      html.A('Dash/Plot.ly', href='https://plot.ly/dash/')]),
                                                   html.Div(className='three columns',
                                                            children=[html.P('Developed by:'),
                                                                      html.A('Mrigank Sondhi', href='https://www.linkedin.com/in/mrigank-sondhi/')])],
                                         style={'marginLeft': 70, 'fontSize': 16}),
                                dcc.Interval(id='interval-component-slow',
                                             interval=1*10000, # in milliseconds
                                             n_intervals=0)], 
                      style={'padding': '20px'})

#Multiple components can update everytime an interval gets fired.
#html.Div(id='live-update-graph') describes the top part of the dashboard in the application, including descriptions for tweet number and potential impressions.
@app.callback(Output('live-update-graph', 'children'), [Input('interval-component-slow', 'n_intervals')])

def update_graph_live(n):
    #Loading data from Heroku PostgreSQL database
    DATABASE_URL = os.environ['DATABASE_URL']
    connection = psycopg2.connect(DATABASE_URL, sslmode='require')
    query = f"SELECT tweet_id, text, created_at, polarity, user_location, user_followers_count FROM {settings.TABLE_NAME}"
    df = pd.read_sql(query, con=connection)

    #Convert UTC to PDT (Pacific Daylight Time)
    df['created_at'] = pd.to_datetime(df['created_at']).apply(lambda x: x - datetime.timedelta(hours=7))

    #Clean and transform the data to enable time series analysis
    result = df.groupby([pd.Grouper(key='created_at', freq='10s'), 'polarity']).count().unstack(fill_value=0).stack().reset_index()
    result = result.rename(columns={"tweet_id":f"Number of '{settings.TRACK_WORDS}' mentions", "created_at":"Time"})  
    time_series = result["Time"][result['polarity']==0].reset_index(drop=True)
    min10 = datetime.datetime.now() - datetime.timedelta(hours=7, minutes=10)
    min20 = datetime.datetime.now() - datetime.timedelta(hours=7, minutes=20)

    neutrals = result[result['Time']>min10][f"Number of '{settings.TRACK_WORDS}' mentions"][result['polarity']==0].sum()
    negatives = result[result['Time']>min10][f"Number of '{settings.TRACK_WORDS}' mentions"][result['polarity']==-1].sum()
    positives = result[result['Time']>min10][f"Number of '{settings.TRACK_WORDS}' mentions"][result['polarity']==1].sum()
    
    #Loading summary data
    query = "SELECT daily_tweets_num, impressions FROM summary;"
    summary = pd.read_sql(query, con=connection)  
    daily_tweets_num = summary['daily_tweets_num'].iloc[0] + result[-6:-3][f"Number of '{settings.TRACK_WORDS}' mentions"].sum()
    daily_impressions = summary['impressions'].iloc[0] + df[df['created_at'] > (datetime.datetime.now() - datetime.timedelta(hours=7, seconds=10))]['user_followers_count'].sum()
    
    cursor = connection.cursor()
    PDT_now = datetime.datetime.now() - datetime.timedelta(hours=7)
    if PDT_now.strftime("%H%M")=='0000':
        cursor.execute("UPDATE summary SET daily_tweets_num = 0, impressions = 0;")
    else:
        cursor.execute(f"UPDATE summary SET daily_tweets_num = {daily_tweets_num}, impressions = {daily_impressions};")
    connection.commit()
    cursor.close()
    connection.close()

    #Percentage change of the Number of Tweets in the last 10 minutes, compared to the previous 10 minutes
    count_now = df[df['created_at'] > min10]['tweet_id'].count()
    count_before = df[(min20 < df['created_at']) & (df['created_at'] < min10)]['tweet_id'].count()
    percent = (count_now-count_before)/count_before*100
    
    #Create the graph 
    children = [html.Div([html.Div([dcc.Graph(id='crossfilter-indicator-scatter', 
                                              figure={'data': [go.Scatter(x=time_series,
                                                                          y=result[f"Number of '{settings.TRACK_WORDS}' mentions"][result['polarity']==0].reset_index(drop=True),
                                                                          name="Neutral",
                                                                          opacity=0.8,
                                                                          mode='lines',
                                                                          line=dict(width=0.5, color='rgb(131, 90, 241)'),
                                                                          stackgroup='one'),
                                                               go.Scatter(x=time_series,
                                                                          y=result[f"Number of '{settings.TRACK_WORDS}' mentions"][result['polarity']==-1].reset_index(drop=True).apply(lambda x: -x),
                                                                          name="Negative",
                                                                          opacity=0.8,
                                                                          mode='lines',
                                                                          line=dict(width=0.5, color='rgb(255, 50, 50)'),
                                                                          stackgroup='two' 
                                                     ),
                                                               go.Scatter(x=time_series,
                                                                          y=result[f"Number of '{settings.TRACK_WORDS}' mentions"][result['polarity']==1].reset_index(drop=True),
                                                                          name="Positive",
                                                                          opacity=0.8,
                                                                          mode='lines',
                                                                          line=dict(width=0.5, color='rgb(184, 247, 212)'),
                                                                          stackgroup='three' 
                                                                         )]})], 
                                   style={'width': '73%', 'display': 'inline-block', 'padding': '0 0 0 20'}),
                          html.Div([dcc.Graph(id='pie-chart',
                                              figure={'data': [go.Pie(labels=['Positive', 'Negative', 'Neutral'], 
                                                                      values=[positives, negatives, neutrals],
                                                                      name="View Metrics",
                                                                      marker_colors=['rgba(184, 247, 212, 0.6)','rgba(255, 50, 50, 0.6)','rgba(131, 90, 241, 0.6)'],
                                                                      textinfo='value',
                                                                      hole=.65)],
                                                      'layout':{'showlegend':False,
                                                                'title':'Tweets in the last 10 minutes',
                                                                'annotations':[
                                                                    dict(text='{0:.1f}K'.format((positives + negatives + neutrals)/1000),
                                                                         font=dict(size=40),
                                                                         showarrow=False)]}})],
                                   style={'width': '27%', 'display': 'inline-block'})]),
                html.Div(className='row',
                         children=[html.Div(children=[html.P('Tweets/10 minutes Changed By', style={'fontSize': 17}),
                                                      html.P('{0:.2f}%'.format(percent) if percent <= 0 else ' {0:.2f}%'.format(percent), style={'fontSize': 40})], 
                                            style={'width': '20%', 'display': 'inline-block'}),
                                   html.Div(children=[html.P('Potential Impressions Today', style={'fontSize': 17}),
                                                      html.P('{0:.1f}K'.format(daily_impressions/1000) if daily_impressions < 1000000 else ('{0:.1f}M'.format(daily_impressions/1000000) if daily_impressions < 1000000000 else '{0:.1f}B'.format(daily_impressions/1000000000)),
                                                             style={'fontSize': 40})], 
                                            style={'width': '20%', 'display': 'inline-block'}),
                                   html.Div(children=[html.P('Tweets Posted Today', style={'fontSize': 17}),
                                                      html.P('{0:.1f}K'.format(daily_tweets_num/1000), 
                                                             style={'fontSize': 40})], 
                                            style={'width': '20%', 'display': 'inline-block'}),
                                   html.Div(children=[html.P(f"Currently tracking \"{settings.TRACK_WORDS}\" (NASDAQ: FB) on Twitter in Pacific Daylight Time (PDT).", style={'fontSize': 25})], 
                                            style={'width': '40%', 'display': 'inline-block'})],
                         style={'marginLeft': 70})]
    return children

#html.Div(id='live-update-graph-bottom') describes the bottom part of the dashboard in the web app.
@app.callback(Output('live-update-graph-bottom', 'children'), [Input('interval-component-slow', 'n_intervals')])

def update_graph_bottom_live(n):
    #Loading data from Heroku PostgreSQL
    DATABASE_URL = os.environ['DATABASE_URL']
    connection = psycopg2.connect(DATABASE_URL, sslmode='require')
    query = f"SELECT tweet_id, text, created_at, polarity, user_location FROM {settings.TABLE_NAME}"
    df = pd.read_sql(query, con=connection)
    connection.close()

    #Convert UTC to PDT
    df['created_at'] = pd.to_datetime(df['created_at']).apply(lambda x: x - datetime.timedelta(hours=7))

    #Clean and transform the data to enable word frequency
    data = ' '.join(df["text"])
    data = re.sub(r"http\S+", "", data)
    data = data.replace('RT ', ' ').replace('&amp;', 'and')
    data = re.sub('[^A-Za-z0-9]+', ' ', data)
    data = data.lower()

    #Filter constants for states in US
    STATES = ['Alabama', 'AL', 'Alaska', 'AK', 'American Samoa', 'AS', 'Arizona', 'AZ', 'Arkansas', 'AR', 'California', 'CA', 'Colorado', 'CO', 'Connecticut', 'CT', 'Delaware', 'DE', 'District of Columbia', 'DC', 'Federated States of Micronesia', 'FM', 'Florida', 'FL', 'Georgia', 'GA', 'Guam', 'GU', 'Hawaii', 'HI', 'Idaho', 'ID', 'Illinois', 'IL', 'Indiana', 'IN', 'Iowa', 'IA', 'Kansas', 'KS', 'Kentucky', 'KY', 'Louisiana', 'LA', 'Maine', 'ME', 'Marshall Islands', 'MH', 'Maryland', 'MD', 'Massachusetts', 'MA', 'Michigan', 'MI', 'Minnesota', 'MN', 'Mississippi', 'MS', 'Missouri', 'MO', 'Montana', 'MT', 'Nebraska', 'NE', 'Nevada', 'NV', 'New Hampshire', 'NH', 'New Jersey', 'NJ', 'New Mexico', 'NM', 'New York', 'NY', 'North Carolina', 'NC', 'North Dakota', 'ND', 'Northern Mariana Islands', 'MP', 'Ohio', 'OH', 'Oklahoma', 'OK', 'Oregon', 'OR', 'Palau', 'PW', 'Pennsylvania', 'PA', 'Puerto Rico', 'PR', 'Rhode Island', 'RI', 'South Carolina', 'SC', 'South Dakota', 'SD', 'Tennessee', 'TN', 'Texas', 'TX', 'Utah', 'UT', 'Vermont', 'VT', 'Virgin Islands', 'VI', 'Virginia', 'VA', 'Washington', 'WA', 'West Virginia', 'WV', 'Wisconsin', 'WI', 'Wyoming', 'WY']
    STATE_DICTIONARY = dict(itertools.zip_longest(*[iter(STATES)] * 2, fillvalue=""))
    INV_STATE_DICTIONARY = dict((v,k) for k,v in STATE_DICTIONARY.items())

    #Clean and transform data to enable geo-distribution
    US = []
    df = df.fillna(" ")
    for location in df['user_location']:
        flag = False
        for state in STATES:
            if state.lower() in location.lower():
                US.append(STATE_DICTIONARY[state] if state in STATE_DICTIONARY else state)
                flag = True
                break
        if not flag:
            US.append(None)

    geo_distribution = pd.DataFrame(US, columns=['State']).dropna().reset_index()
    geo_distribution = geo_distribution.groupby('State').count().rename(columns={"index": "Number"}).sort_values(by=['Number'], ascending=False).reset_index()
    geo_distribution["Logarithm"] = geo_distribution["Number"].apply(lambda x: math.log(x))
    geo_distribution['Full State Name'] = geo_distribution['State'].apply(lambda x: INV_STATE_DICTIONARY[x])
    geo_distribution['text'] = geo_distribution['Full State Name'] + '<br>' + 'Number: ' + geo_distribution['Number'].astype(str)

    tokenized_word = word_tokenize(data)
    stop_words = set(stopwords.words("english"))
    filtered_sent = []
    for word in tokenized_word:
        if (word not in stop_words) and (len(word) >= 3):
            filtered_sent.append(word)
    frequency_distribution = FreqDist(filtered_sent)
    frequency_distribution = pd.DataFrame(frequency_distribution.most_common(16), columns = ["Word", "Frequency"]).drop([0]).reindex()
    frequency_distribution['Polarity'] = frequency_distribution['Word'].apply(lambda x: TextBlob(x).sentiment.polarity)
    frequency_distribution['Marker_Color'] = frequency_distribution['Polarity'].apply(lambda x: 'rgba(255, 50, 50, 0.6)' if x < -0.1 else ('rgba(184, 247, 212, 0.6)' if x > 0.1 else 'rgba(131, 90, 241, 0.6)'))
    frequency_distribution['Line_Color'] = frequency_distribution['Polarity'].apply(lambda x: 'rgba(255, 50, 50, 1)' if x < -0.1 else ('rgba(184, 247, 212, 1)' if x > 0.1 else 'rgba(131, 90, 241, 1)'))

    #Create the graph 
    children = [html.Div([dcc.Graph(id='x-time-series',
                                    figure = {'data':[go.Bar(x=frequency_distribution["Frequency"].loc[::-1],
                                                             y=frequency_distribution["Word"].loc[::-1], 
                                                             name="Neutrals", 
                                                             orientation='h',
                                                             marker_color=frequency_distribution['Marker_Color'].loc[::-1].to_list(),
                                                             marker=dict(
                                                                 line=dict(color=frequency_distribution['Line_Color'].loc[::-1].to_list(),
                                                                           width=1)))],
                                              'layout':{'hovermode':"closest"}})],
                         style={'width': '49%', 'display': 'inline-block', 'padding': '0 0 0 20'}),
                html.Div([dcc.Graph(id='y-time-series',
                                    figure = {'data':[go.Choropleth(locations=geo_distribution['State'], #Spatial coordinates
                                                                    z = geo_distribution['Logarithm'].astype(float), #Data to be color-coded
                                                                    locationmode = 'USA-states', #set of locations match entries in `locations` 
                                                                    text=geo_distribution['text'], #hover text
                                                                    geo = 'geo',
                                                                    colorbar_title = "Number in natural log",
                                                                    marker_line_color='white',
                                                                    colorscale = ["#fdf7ff", "#835af1"])],
                                              'layout': {'title': "Geographic Segmentation of the Unites States",
                                                         'geo':{'scope':'usa'}}})], 
                         style={'display': 'inline-block', 'width': '49%'})]
    return children

if __name__ == '__main__':
    app.run_server(debug=True)