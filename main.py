from flask import Flask, Markup, flash, render_template, request, session, url_for, redirect
import pymysql.cursors
import MySQLdb
import functools
from flask_socketio import *
#from flask_socketio import SocketIO, disconnect
from flask_login import LoginManager, current_user, UserMixin, login_required, login_user, logout_user

app = Flask(__name__)
app.config['SECRET_KEY'] = 'vnkdjnfjknfl1232#'
socketio = SocketIO(app)
login_manager = LoginManager(app)
#login_manager.init_app(app)
conn = pymysql.connect(host='192.168.64.2',
                       user='user',
                       password='',
                       db='chat_system',
                       charset='utf8mb4',
                       cursorclass=pymysql.cursors.DictCursor) 

def authenticated_only(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            disconnect()
        else:
            return f(*args, **kwargs)
    return wrapped

class User(UserMixin):
    def __init__(self, username):
        self.id=username

    @property
    def is_active(self):
        return True

    @property
    def is_authenticated(self):
        cursor=conn.cursor()
        query='select * from user where username = %s'
        cursor.execute(query, (self.id,))
        data=cursor.fetchone()
        cursor.close()
        if(data):
            return True
        else:
            return False

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return self.id

@login_manager.user_loader
def load_user(user_id):
    cursor=conn.cursor()
    query='select * from user where username = %s'
    cursor.execute(query, user_id)
    data=cursor.fetchone()
    cursor.close()
    if(data):
        return User(user_id)
    else:
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login_page')
def login_page():
    return render_template('login_page.html', error=None)

@app.route('/register_page')
def register_page():
    return render_template('register_page.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    username=request.form['username']
    #check duplicate login
    cursor=conn.cursor()
    query='select * from user where username = %s and online = %s'
    cursor.execute(query, (username, 1))
    data=cursor.fetchone()
    cursor.close()
    if(data): #we have duplicate login
        return render_template('login_page.html', error="This user has already been logged in.")
    user=User(username)
    if user.is_authenticated:
        login_user(user)
        #todo update user active status
        cursor=conn.cursor()
        query='update user set online = 1 where username = %s'
        cursor.execute(query, (username,))
        conn.commit()
        cursor.close()
        flash('Logged in successfully.')
        return redirect(url_for('home'))
    else:
        return render_template('login_page.html', error="Please register your username first.")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login_page'))


@app.route('/home')
@login_required
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    username=request.form['username']
    cursor=conn.cursor()
    query='select * from user where username = %s'
    cursor.execute(query, (username,))
    data=cursor.fetchone()
    error=None
    cursor.close()
    if(data):
        error='This username has already been registered.'
        return render_template('register_page.html', error=error)
    else:
        cursor=conn.cursor()
        ins='insert into user VALUES(%s, %s, %s)'
        cursor.execute(ins, (username, 0, None))
        conn.commit()
        cursor.close()
        return render_template('index.html')

@socketio.on('connect')
def connect_handler():
    if current_user.is_authenticated:
        assigned_room_number=fetch_room_number(current_user.id)
        cursor=conn.cursor()
        query='update user set online = %s, chat_room_id = %s where username = %s'
        cursor.execute(query,(1, assigned_room_number, current_user.id))
        conn.commit()
        cursor.close()
        join_room(assigned_room_number)
        print('User ', current_user.id, 'has now connected to the server')
        online_user_list=get_all_online_users()
        emit('connection ack', {'msg':'success'})
        socketio.emit('online user list', online_user_list)
    else:
        return False

@socketio.on('join')
@authenticated_only
def join_handler(data):
    target_username=data['username']
    #check if target is indeed an online user first
    is_valid_target, room_number, error=is_valid_online_user(current_user.id, target_username)
    if(is_valid_target):
        join_room(room_number)
        #update current user chat_room_id
        cursor=conn.cursor()
        query='update user set chat_room_id = %s where username = %s'
        cursor.execute(query, (room_number, current_user.id))
        conn.commit()
        cursor.close()
        print('User ', current_user.id, ' has now joined the room ', target_username, ' is in.')
        online_user_list=get_all_online_users()
        socketio.emit('online user list', online_user_list)
        socketio.emit('join ack', {'msg':'success', 'new_user': current_user.id, 'target_user': target_username, 'room_number': room_number}, room=room_number)
    else:
        print('User ', current_user.id, 'has tried to join the room ', target_username, ' is in but failed.')
        socketio.emit('join ack', {'msg':'failure', 'new_user': current_user.id, 'target_user': target_username, 'error':error}, room=room_number)

@socketio.on('send chat message')
@authenticated_only
def send_chat_message_handler(data):
    msg=data['message']
    username=current_user.id
    room_number=get_authenticated_user_room_number(username)
    socketio.emit('chat message ack', {'username':username, 'message':msg}, room=room_number)

@socketio.on('quit chat group')
@authenticated_only
def quit_chat_group_handler(data):
    username=current_user.id
    room_number=get_authenticated_user_room_number(username)
    leave_room(room_number)
    new_room_number=get_new_room_number(username)
    join_room(new_room_number)
    #TODO:update room number for this user
    cursor=conn.cursor()
    query='update user set chat_room_id = %s where username = %s'
    cursor.execute(query, (new_room_number, username))
    conn.commit()
    cursor.close()
    #we let this user know that the transaction is a success first
    online_user_list=get_all_online_users()
    socketio.emit('online user list', online_user_list)
    emit('quit chat ack', {'msg':'success', 'left_user':username})
    #TODO:check remaining clients in old room number
    remaining_num=count_remaining_clients(room_number)
    if(remaining_num>1):
        #no need to close this chat
        socketio.emit('quit chat ack', {'msg':'update', 'left_user':username}, room=room_number)
    else:
        #we need to close this chat. Find the remaining user. He/She will have this room.
        remaining_client_username=get_last_remaining_client(room_number)
        socketio.emit('quit chat ack', {'msg':'forced leave', 'left_user':username}, room=room_number)

@socketio.on('disconnect')
def disconnect_handler():
    if current_user.is_authenticated:
        #first we need to deal with other users in the same room
        room_number=get_authenticated_user_room_number(current_user.id)
        remaining_num=count_remaining_clients(room_number)
        if(remaining_num>1):
            socketio.emit('quit chat ack', {'msg':'update', 'left_user':current_user.id}, room=room_number)
        else:
            remaining_client_username=get_last_remaining_client(room_number)
            socketio.emit('quit chat ack', {'msg':'forced leave', 'left_user':current_user.id}, room=room_number)
        #next we update the online & chat room id field of this user
        cursor=conn.cursor()
        query='update user set online = %s, chat_room_id = %s where username = %s'
        cursor.execute(query,(0, None, current_user.id))
        conn.commit()
        cursor.close()
        online_user_list=get_all_online_users()
        socketio.emit('online user list', online_user_list)
        print('User ', current_user.id, ' has now disconnected from the server')
        emit('disconnection ack',{'msg':'success'})
    else:
        pass

def get_all_online_users():
    cursor=conn.cursor()
    query='select username, chat_room_id from user where online = %s'
    cursor.execute(query, 1)
    data=cursor.fetchall()
    cursor.close()
    online_user_list={}
    if(data):
        for item in data:
            username=item['username']
            chat_room_id=int(item['chat_room_id'])
            online_user_list[username]=chat_room_id
    return online_user_list

def get_last_remaining_client(room_number):
    cursor=conn.cursor()
    query='select username from user where chat_room_id = %s'
    cursor.execute(query, (room_number,))
    data=cursor.fetchone()
    cursor.close()
    name=data['username']
    return name

def count_remaining_clients(room_number):
    cursor=conn.cursor()
    query='select count(*) as remaining_num from user where chat_room_id = %s'
    cursor.execute(query, (room_number,))
    data=cursor.fetchone()
    cursor.close()
    remaining_num=int(data['remaining_num'])
    return remaining_num

def get_authenticated_user_room_number(username):
    cursor=conn.cursor()
    query='select chat_room_id from user where username = %s'
    cursor.execute(query, (username,))
    data=cursor.fetchone()
    cursor.close()
    if data['chat_room_id'] is not None:
        room_number=int(data['chat_room_id'])
    else:
        room_number=None
    return room_number

def is_valid_online_user(current_username, target_username):
    room_number=None
    error=None
    cursor=conn.cursor()
    query='select * from user where username = %s'
    cursor.execute(query, (target_username,))
    data=cursor.fetchone()
    cursor.close()
    if(data):
        is_online=int(data['online'])
        if(is_online):
            if(current_username!=target_username):
                room_number=int(data['chat_room_id'])
                return True, room_number, error
            else:
                error='target user is current user'
                return False, room_number, error
        else:
            error='target user is offline.'
            return False, room_number, error
    else:
        error='target user does not exist.'
        return False, room_number, error

def get_new_room_number(username):
    #assign a new room number for this user
    cursor=conn.cursor()
    query='select IFNULL(MAX(chat_room_id), 0) as chat_room_id from user'
    cursor.execute(query)
    data=cursor.fetchone()
    cursor.close()
    new_room_number=int(data['chat_room_id'])+1
    return new_room_number

def fetch_room_number(username):
    cursor=conn.cursor()
    #find if this user already has a room number or not
    query='select chat_room_id from user where username=%s'
    cursor.execute(query, (username,))
    data=cursor.fetchone()
    cursor.close()
    if(data):
        if data['chat_room_id'] is not None:
            new_room_number=int(data['chat_room_id'])
            return new_room_number
    #assign a new room number for this user
    cursor=conn.cursor()
    query='select IFNULL(MAX(chat_room_id), 0) as chat_room_id from user'
    cursor.execute(query)
    data=cursor.fetchone()
    cursor.close()
    new_room_number=int(data['chat_room_id'])+1
    return new_room_number

if __name__ == '__main__':
    socketio.run(app, debug=True)
