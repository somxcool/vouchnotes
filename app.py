## Start

from flask import Flask, render_template, g, current_app, flash, request, redirect, url_for, send_file, session, send_from_directory
from flask_login import LoginManager, login_required, UserMixin, login_user, current_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix
import requests as getfromapi
import firebase_admin
from firebase_admin import credentials, auth
from datetime import date
import json
import ast
import uuid
import orjson
from apscheduler.schedulers.background import BackgroundScheduler
from flask_sitemapper import Sitemapper

gcred = credentials.Certificate('credcert.json')
default_app = firebase_admin.initialize_app(gcred)
token_info = gcred.get_access_token()

sitemapper = Sitemapper()

# Refreshing the Firebase API token every 50 minutes
def regenerate_oauth_token():
    print('Regenerating...')
    global gcred
    global oauth_token
    global bearer
    global sql_headers
    token_info = gcred.get_access_token()
    oauth_token = token_info.access_token

    bearer = 'Bearer ' + oauth_token

    sql_headers = {
        'Authorization': bearer,
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }

oauth_token = token_info.access_token

sched = BackgroundScheduler(daemon=True)
sched.add_job(regenerate_oauth_token, 'interval', minutes=50)
sched.start()

bearer = 'Bearer ' + oauth_token

sql_headers = {
    'Authorization': bearer,
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

getfromapi_headers = {
    'User-Agent': 'Vouchnotes/0.1 https://maximus.cool',
    'From': '*put your email here*',
    'Authorization': 'Discogs token=*put your discogs token here*'
}

firebase_headers = {
    'Content-Type': 'application/json'
}

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your secret key'

sitemapper.init_app(app)

login = LoginManager()
login.init_app(app)
login.login_view = 'signin'
login.login_message = 'Please sign in.'

class Brocker(UserMixin):
    def __init__(self, authId, email, displayName):
        self.id = authId
        self.email = email
        self.displayName = displayName

def get_userkey():
    if current_user.is_authenticated:
        payload = {
            'operationName': 'GetUserByAuthId',
            'variables': {
                'targetAuthId': current_user.id
            }
        }
        response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
        jsonresponse = orjson.loads(response.content)
        tlist = jsonresponse['data']['users']
        thekee = tlist[0]['id']
        return thekee

@login.user_loader
def load_user(authId):
    brocker = auth.get_user(authId)

    if brocker:
        return Brocker(brocker.uid, brocker.email, brocker.display_name)
        print('user loaded')
    else:
        print("user not loaded")
        return None

@sitemapper.include()
@app.route('/sign-in', methods=('GET', 'POST'))
def vsignin():

    if request.method == 'POST':
        user_email = request.form['user_email']
        user_password = request.form['user_password']

        payload = {
            'email': user_email,
            'password': user_password,
            'returnSecureToken':'true'
        }
        response = getfromapi.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=', json=payload, headers=firebase_headers)
        jsonresponse = response.json()
        print(jsonresponse)
        if response.status_code == 200:
            brocker = Brocker(jsonresponse['localId'], jsonresponse['email'], jsonresponse['displayName'])
            login_user(brocker)

            # Getting user id from SQL using authId (localId) to store it in the session
            payload = {
                'operationName': 'GetUserByAuthId',
                'variables': {
                    'targetAuthId': jsonresponse['localId']
                }
            }
            response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
            jsonresponse = response.json()
            tlist = jsonresponse['data']['users']
            session['user_key'] = tlist[0]['id'] # Storing sql id as user_key in the session

            return redirect(url_for('vprofile', thedisplayname=brocker.displayName))

    return render_template('signin.html')

@sitemapper.include()
@app.route('/sign-up', methods=('GET', 'POST'))
def vsignup():

    if request.method == 'POST':
        username = request.form['username']
        user_email = request.form['user_email']
        user_password = request.form['user_password']

        # Checking if user with the same display name already exists in the SQL db
        payload = {
            'operationName': 'GetUserByDisplayName',
            'variables': {
                'targetDisplayName': username
            }
        }
        response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
        jsonresponse = response.json()
        print(jsonresponse)
        tlist = jsonresponse['data']['users']
        if tlist: # if the user exists, redirect to choose a different username
            session['registererror'] = 'This username is already taken. Choose a different one.'
            return redirect(url_for('vsignup'))

        auth.create_user(display_name=username, email=user_email, password=user_password)
        payload = {
            'email': user_email,
            'password': user_password,
            'returnSecureToken': 'true'
        }
        # For this one I used a different key than for the rest of the requests
        response = getfromapi.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=', json=payload, headers=firebase_headers)
        jsonresponse = response.json() # Signing In
        print('signing in', jsonresponse)

        if response.status_code == 200:

            sqlurl = 'https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key='

            # Creating SQL user record
            payload = {
                'operationName': 'CreateUser',
                'variables': {
                    'authId': jsonresponse['localId'],
                    'displayName': jsonresponse['displayName'],
                    'createdDate': date.today().isoformat()
                }
            }

            sqlresponse = getfromapi.post(sqlurl, json=payload, headers=sql_headers) # User record created in SQL Connect
            # print('creating sql user', sqlresponse.json())
            jsonsqlresponse = sqlresponse.json()
            session['user_key'] = jsonsqlresponse['data']['user_insert']['id'] # Storing sql id in session
            # sqljsonresponse = sqlresponse.json()
            # sqlId = sqljsonresponse['data']['user_insert']['id']
            brocker = Brocker(jsonresponse['localId'], jsonresponse['email'], jsonresponse['displayName'])
            login_user(brocker)
            # print(sqljsonresponse)
            session['registererror'] = None
            return redirect(url_for('vsearch'))
        
    return render_template('signup.html')

@sitemapper.include()
@app.route('/daily-album')
def vdailyalbum():
    if current_user.is_authenticated and not session['user_key']:
        session['user_key'] = get_userkey()
    return render_template('dailyalbum.html')

@app.route('/@<string:thedisplayname>', methods=('GET', 'POST'))
def vprofile(thedisplayname):
    if current_user.is_authenticated and not session['user_key']:
        session['user_key'] = get_userkey()

    if request.method == 'POST':

        if 'following_name' in request.form:

            following_name = request.form['following_name']

            # Creating a follow
            payload = {
                'operationName': 'CreateFollow',
                'variables': {
                    'follower': session['user_key'],
                    'following': following_name
                }
            }
            response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key=', json=payload, headers=sql_headers)
            jsonresponse = response.json()
            print('creating a follow', jsonresponse)

        if 'follow_id' in request.form:
            follow_id = request.form['follow_id']
            print(follow_id)


            # Deleting a follow
            payload = {
                'operationName': 'DeleteFollow',
                'variables': {
                    'id': follow_id
                }
            }
            response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key=', json=payload, headers=sql_headers)
            jsonresponse = orjson.loads(response.content)
            print(jsonresponse)
            return redirect(url_for('vprofile', thedisplayname=thedisplayname))


    with getfromapi.Session() as api_session:
        # Getting SQL user id from SQL by using display name
        payload = {
            'operationName': 'GetUserByDisplayName',
            'variables': {
                'targetDisplayName': thedisplayname
            }
        }
        response = api_session.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
        jsonresponse = orjson.loads(response.content)
        # print(jsonresponse)
        tlist = jsonresponse['data']['users']
        theuserkey = tlist[0]['id']

        # Having the userId, query SQL for all their recommendations
        payload = {
            'operationName': 'GetRecommendationsByUserId',
            'variables': {
                'userId': theuserkey
            }
        }
        response = api_session.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
        jsonresponse = orjson.loads(response.content)
        print(jsonresponse)
        user_recommendations = jsonresponse['data']['recommendations']
        user_rec_count = len(user_recommendations)
        total_user_likes = 0
        for rec in user_recommendations:
            total_user_likes += rec['likes']
        
        if current_user.is_authenticated:
            # Checking if a follow exists
            payload = {
                'operationName': 'GetFollowByFilter',
                'variables': {
                    'follower': session['user_key'],
                    'following': theuserkey
                }
            }
            response = api_session.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
            jsonresponse = orjson.loads(response.content)
            print('orjson', jsonresponse)
            responselist = jsonresponse['data']['follows']
            if len(responselist) > 0:
                follow_id = responselist[0]['id']
                print('yes')
                following_already = 'good'
            else:
                print('no')
                following_already = None
                follow_id = None
        else:
            following_already = None
            follow_id = None

    return render_template('profile.html', thedisplayname=thedisplayname, user_recommendations=user_recommendations, user_rec_count=user_rec_count, total_user_likes=total_user_likes, theuserkey=theuserkey, following_already=following_already, follow_id=follow_id)

@sitemapper.include()
@app.route('/search', methods=('GET', 'POST'))
def vsearch():
    if current_user.is_authenticated and not session['user_key']:
        session['user_key'] = get_userkey()
    
    base_api_url = 'https://api.discogs.com/database/search?q='
    jsonresponse = None
    all_releases = []

    if request.method == 'POST':
        if 'search_request' in request.form:
            search_request = request.form['search_request']
            search_request = search_request.replace(' ', '%20')
            final_api_url = base_api_url + search_request
            response = getfromapi.get(final_api_url, headers=getfromapi_headers)
            jsonresponse = response.json()
            master_ids = set()
            all_releases = []
            for an_entry in jsonresponse['results']:
                if an_entry['type'] == 'master':
                    if an_entry['master_id'] in master_ids:
                        pass
                    else:
                        master_ids.add(an_entry['id'])
                        all_releases.append(an_entry)
                if an_entry['type'] == 'release':
                    if an_entry['master_id'] in master_ids:
                        pass
                    else:
                        master_ids.add(an_entry['master_id'])
                        all_releases.append(an_entry)

        if 'record_id' in request.form:
            session['record_id'] = request.form['record_id']
            session['record_mid'] = request.form['record_mid']
            if session['record_mid'] == '0':
                session['record_mid'] = session['record_id']
            session['record_title'] = request.form['record_title']
            session['record_cover'] = request.form['record_cover']
            session['record_genres'] = request.form['record_genres']

            return redirect(url_for('vrecommend'))

    return render_template('search.html', all_releases=all_releases, jsonresponse=jsonresponse)

@sitemapper.include()
@app.route('/')
def vindex():
    return redirect(url_for('vhomeall'))

@sitemapper.include()
@app.route('/home/all', methods=('GET', 'POST'))
def vhomeall():
    if current_user.is_authenticated and not session['user_key']:
        print('YEH')
        session['user_key'] = get_userkey()

    # Listing all recommendations
    callingurl = 'https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key='
    payload = {
        'operationName': 'ListRecommendations'
    }
    response = getfromapi.post(callingurl, json=payload, headers=sql_headers)
    jsonresponse = response.json()
    print('home', jsonresponse)
    recommendations_list = jsonresponse['data']['recommendations']


    if request.method == 'POST':
        recId_liked = request.form['recId_liked']
        rec_user_id = request.form['rec_user_id']
        if not current_user.is_authenticated:
            return redirect(url_for('vsignin'))
        if session['user_key'] == rec_user_id:
            return redirect(url_for('vhomeall'))

        print(session['user_key'])
        
        # Check if a like exists
        payload = {
            'operationName': 'GetLikeByUserAndRecommendationIds',
            'variables': {
                'user': session['user_key'],
                'recommendation': recId_liked
            }
        }
        response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
        jsonresponse = response.json()
        print('Checking if a like exists', jsonresponse)
        checklist = jsonresponse['data']['likes']
        if not checklist:
            # Creating a Like
            payload = {
                'operationName': 'CreateLike',
                'variables': {
                    'user': session['user_key'],
                    'recommendation': recId_liked
                }
            }
            response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key=', json=payload, headers=sql_headers)
            jsonresponse = response.json()
            print('Creating a like', jsonresponse)

            # Actually increasing the like count of the recommendation
            payload = {
                'operationName': 'UpdateRecommendationLikes',
                'variables': {
                    'recommendation': recId_liked,
                    'likesIncrement': 1
                }
            }
            response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key=', json=payload, headers=sql_headers)
            jsonresponse = response.json()
            print(jsonresponse)
            return redirect(url_for('vhomeall'))


    return render_template('home.html', recommendations_list=recommendations_list)

@sitemapper.include()
@app.route('/home/following', methods=('GET', 'POST'))
@login_required
def vhomefollowing():
    if current_user.is_authenticated and not session['user_key']:
        session['user_key'] = get_userkey()


    # Getting user following list first, then user's recommendations
    with getfromapi.Session() as api_session:
        print('starting')
        payload = {
            'operationName': 'ListRecommendations'
        }
        response_a = api_session.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)

        payload = {
            'operationName': 'GetFollowByFollowerId',
            'variables': {
                'follower': session['user_key']
            }
        }
        response_b = api_session.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)

        # Making a list of ID's of users that we follow
        jsonresponse_b = orjson.loads(response_b.content)
        id_prelist = jsonresponse_b['data']['follows']
        id_list = []
        for athing in id_prelist:
            id_list.append(athing['followingId'])
        print(id_list)

        # Only saving the recommendations that those users recommended

        jsonresponse_a = orjson.loads(response_a.content)
        recommendations_prelist = jsonresponse_a['data']['recommendations']
        recommendations_list = []
        for rec in recommendations_prelist:
            if rec['user']['id'] in id_list:
                recommendations_list.append(rec)
        print(recommendations_list)

        if request.method == 'POST':
            recId_liked = request.form['recId_liked']
            rec_user_id = request.form['rec_user_id']
            if session['user_key'] == rec_user_id:
                return redirect(url_for('vhomeall'))

            print(session['user_key'])
            
            # Check if a like exists
            payload = {
                'operationName': 'GetLikeByUserAndRecommendationIds',
                'variables': {
                    'user': session['user_key'],
                    'recommendation': recId_liked
                }
            }
            response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
            jsonresponse = response.json()
            print('Checking if a like exists', jsonresponse)
            checklist = jsonresponse['data']['likes']
            if not checklist:
                # Creating a Like
                payload = {
                    'operationName': 'CreateLike',
                    'variables': {
                        'user': session['user_key'],
                        'recommendation': recId_liked
                    }
                }
                response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key=', json=payload, headers=sql_headers)
                jsonresponse = response.json()
                print('Creating a like', jsonresponse)

                # Actually increasing the like count of the recommendation
                payload = {
                    'operationName': 'UpdateRecommendationLikes',
                    'variables': {
                        'recommendation': recId_liked,
                        'likesIncrement': 1
                    }
                }
                response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key=', json=payload, headers=sql_headers)
                jsonresponse = response.json()
                print(jsonresponse)
                return redirect(url_for('vhomefollowing'))


    return render_template('home.html', recommendations_list=recommendations_list)

@sitemapper.include()
@app.route('/recommend', methods=('GET', 'POST'))
@login_required
def vrecommend():

    jsonresponse = None
    parsed = None
    if request.method == 'POST':

        rec_content = request.form['rec_content']
        #localid = request.form['localid']
        lister = ast.literal_eval(session['record_genres'])

        # Checking if release is in SQL database.
        payload = {
            'operationName': 'GetReleaseByFilter',
            'variables': {
                'masterId': session['record_mid'],
                'regId': session['record_id']
            }
        }
        response = getfromapi.post('https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeQuery?key=', json=payload, headers=sql_headers)
        jsonresponse = response.json()
        print('checking if release exists', jsonresponse)
        responselist = jsonresponse['data']['releases']
        
        if not responselist:
            # print('Checking if it exists', jsonresponse)

            # CreateRelease Mutation
            sqlurl = 'https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key='
            payload = {
                'operationName': 'CreateRelease',
                'variables': {
                    'title': session['record_title'],
                    'masterId': session['record_mid'],
                    'regId': session['record_id'],
                    'imageUrl': session['record_cover'],
                    'genres': lister
                }
            }
            response = getfromapi.post(sqlurl, json=payload, headers=sql_headers)
            jsonresponse = response.json()
            print('creatin release', jsonresponse)

            releasekey = jsonresponse['data']['release_insert']['id']
        else:
            tlist = jsonresponse['data']['releases']
            print(tlist)
            releasekey = tlist[0]['id']

        callingurl = 'https://firebasedataconnect.googleapis.com/v1/projects/songbrockerz/locations/us-west1/services/songbrockerz-service/connectors/example:executeMutation?key='
        payload = {
            'operationName': 'CreateRecommendation',
            'variables': {
                'release': releasekey,
                'user': session['user_key'],
                'recText': rec_content,
                'likes': 0
            }
        }
        response = getfromapi.post(callingurl, json=payload, headers=sql_headers)
        jsonresponse = response.json()
        
        print('This is the result of creating a recommendation,', jsonresponse)
        return redirect(url_for('vsearch'))

    return render_template('recommend.html', jsonresponse=jsonresponse, parsed=parsed)

@sitemapper.include()
@app.route('/about-us')
def vaboutus():
    return render_template('aboutus.html')

@sitemapper.include()
@app.route('/contact')
def vcontact():
    return render_template('contact.html')

@app.route('/out')
def vout():
    logout_user()
    return redirect(url_for('vhomeall'))

@app.route('/robots.txt')
def vrobotstxt():
    return send_from_directory(app.static_folder, 'robots.txt')

@app.route('/sitemap.xml')
def vsitemapxml():
    return sitemapper.generate()