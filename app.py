import os  
import io  
import json  
import csv  
from datetime import datetime, timedelta, date  
  
from flask import (  
    Flask, render_template, request, redirect, url_for, flash, Response, jsonify, send_file  
)  
from flask_login import (  
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user  
)  
from flask_bcrypt import Bcrypt  
from pymongo import MongoClient, ASCENDING, DESCENDING  
from bson.objectid import ObjectId  
from bson import json_util, regex  
import qrcode  
from dateutil.relativedelta import relativedelta  
from collections import defaultdict  
  
# load environment variables from a .env file if present  
from dotenv import load_dotenv  
load_dotenv()  
  
app = Flask(__name__)  
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a-super-secret-key-that-you-should-change')  
  
# --- Mongo setup ---  
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')  
BASE_URL = os.environ.get('BASE_URL', 'https://famflow.onrender.com')  # Example base URL  
client = MongoClient(MONGO_URI)  
db = client['mchores_app']  # internal DB name  
  
users_collection = db['users']  
events_collection = db['events']  
rewards_collection = db['rewards']  
transactions_collection = db['transactions']  
moods_collection = db['moods']  
  
# Recommended indexes  
users_collection.create_index([('email', ASCENDING)], unique=True, sparse=True)  
users_collection.create_index([('username', ASCENDING), ('family_id', ASCENDING)], unique=True, sparse=True)  
events_collection.create_index([('family_id', ASCENDING), ('due_date', ASCENDING)])  
moods_collection.create_index([('user_id', ASCENDING), ('date', ASCENDING), ('period', ASCENDING)], unique=True)  
moods_collection.create_index([('family_id', ASCENDING), ('date', ASCENDING)])  
  
bcrypt = Bcrypt(app)  
login_manager = LoginManager()  
login_manager.init_app(app)  
login_manager.login_view = 'login'  
  
# --- MoodMatrix Configuration ---  
MOOD_CONFIG = {  
    'moods': [  
        {'emoji': '😖', 'desc': 'Upset',      'score': 1, 'color': '#ef4444'},  
        {'emoji': '😔', 'desc': 'Not Happy',  'score': 2, 'color': '#f97316'},  
        {'emoji': '😌', 'desc': 'Calm / Okay','score': 3, 'color': '#84cc16'},  
        {'emoji': '😎', 'desc': 'Very Happy', 'score': 4, 'color': '#22c55e'}  
    ],  
    'aiApiUrl': 'https://ranfysvalle02--orby-api-ai.modal.run/'  # Example external AI API  
}  
MOOD_EMOJI_TO_SCORE = {m['emoji']: m['score'] for m in MOOD_CONFIG['moods']}  
  
# --- Models ---  
class User(UserMixin):  
    """  
    Each user has:  
      - points: current available points  
      - lifetime_points: total points ever earned (never decreased)  
    """  
    def __init__(self, user_data):  
        self.id = str(user_data['_id'])  
        self.email = user_data.get('email')  
        self.username = user_data.get('username')  
        self.password_hash = user_data['password_hash']  
        self.role = user_data['role']  # 'parent' or 'child'  
        self.family_id = user_data.get('family_id')  
        self.points = user_data.get('points', 0)  
        self.lifetime_points = user_data.get('lifetime_points', 0)  
  
    @staticmethod  
    def get(user_id):  
        try:  
            data = users_collection.find_one({'_id': ObjectId(user_id)})  
            if data:  
                return User(data)  
        except:  
            return None  
        return None  
  
@login_manager.user_loader  
def load_user(user_id):  
    return User.get(user_id)  
  
  
class MongoJsonEncoder(json.JSONEncoder):  
    """Makes Flask able to return ObjectId, datetime, etc. in JSON."""  
    def default(self, obj):  
        if isinstance(obj, (ObjectId, datetime, date)):  
            return str(obj)  
        return json_util.default(obj)  
  
app.json_encoder = MongoJsonEncoder  
  
  
# --- Routes ---  
@app.route('/')  
def index():  
    """ If logged in, go to the family dashboard; otherwise, go to login. """  
    if current_user.is_authenticated:  
        return redirect(url_for('family_dashboard'))  
    return redirect(url_for('login'))  
  
  
@app.route('/login', methods=['GET', 'POST'])  
def login():  
    if current_user.is_authenticated:  
        return redirect(url_for('family_dashboard'))  
    if request.method == 'POST':  
        identifier = request.form['email_or_username']  
        user_data = users_collection.find_one({'$or': [{'email': identifier}, {'username': identifier}]})  
        if user_data and bcrypt.check_password_hash(user_data['password_hash'], request.form['password']):  
            login_user(User(user_data))  
            return redirect(url_for('family_dashboard'))  
        else:  
            flash('Invalid credentials. Please try again.', 'error')  
    return render_template('index.html', page='login')  
  
  
@app.route('/logout')  
@login_required  
def logout():  
    logout_user()  
    return redirect(url_for('login'))  
  
  
@app.route('/join/<invite_code>')  
def join_family(invite_code):  
    """ Child can join the parent's family via this link. """  
    try:  
        parent = users_collection.find_one({'_id': ObjectId(invite_code), 'role': 'parent'})  
        if not parent:  
            flash('This is not a valid invite code.', 'error')  
            return redirect(url_for('login'))  
    except:  
        flash('Invalid invite code format.', 'error')  
        return redirect(url_for('login'))  
    parent_name = parent.get('username', 'your parent')  
    return render_template('index.html', page='join_family', parent_name=parent_name, invite_code=invite_code)  
  
  
@app.route('/register/parent', methods=['GET', 'POST'])  
def register_parent():  
    if request.method == 'POST':  
        email = request.form['email']  
        username = request.form['username']  
        password = request.form['password']  
  
        if users_collection.find_one({'email': email}):  
            flash('Email address already in use.', 'error')  
            return redirect(url_for('register_parent'))  
  
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')  
        new_id = users_collection.insert_one({  
            'email': email,  
            'username': username,  
            'password_hash': hashed_pw,  
            'role': 'parent',  
            'lifetime_points': 0,  
            'points': 0  
        }).inserted_id  
  
        # For a parent, we set their family_id = their own _id  
        users_collection.update_one({'_id': new_id}, {'$set': {'family_id': str(new_id)}})  
  
        flash('Parent account created! Please log in.', 'success')  
        return redirect(url_for('login'))  
  
    return render_template('index.html', page='register_parent')  
  
  
@app.route('/register/child/<invite_code>', methods=['GET', 'POST'])  
def register_child(invite_code):  
    """ Child registration route if they have an invite_code (parent's _id). """  
    try:  
        parent = users_collection.find_one({'_id': ObjectId(invite_code)})  
        if not parent or parent.get('role') != 'parent':  
            flash('Invalid invite code.', 'error')  
            return redirect(url_for('login'))  
    except:  
        flash('Invalid invite code format.', 'error')  
        return redirect(url_for('login'))  
  
    if request.method == 'POST':  
        username = request.form['username']  
        password = request.form['password']  
  
        # Ensure username is unique among that family's children  
        if users_collection.find_one({'username': username, 'family_id': invite_code}):  
            flash('Username already taken in this family.', 'error')  
            return redirect(url_for('register_child', invite_code=invite_code))  
  
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')  
        users_collection.insert_one({  
            'username': username,  
            'password_hash': hashed_pw,  
            'role': 'child',  
            'family_id': invite_code,  
            'points': 0,  
            'lifetime_points': 0  
        })  
        flash('Child account created! You can now log in.', 'success')  
        return redirect(url_for('login'))  
  
    return render_template('index.html', page='register_child', invite_code=invite_code)  
  
  
@app.route('/invite')  
@login_required  
def invite():  
    """ Parent can visit this route to see their unique invite code + QR. """  
    if current_user.role != 'parent':  
        return redirect(url_for('family_dashboard'))  
    return render_template('index.html', page='invite', invite_code=current_user.id)  
  
  
@app.route('/qr_code')  
@login_required  
def qr_code():  
    """ Generate a QR image for the invite link. """  
    if current_user.role != 'parent':  
        return Response(status=403)  
    invite_url = f"{BASE_URL}{url_for('join_family', invite_code=current_user.id)}"  
    img = qrcode.make(invite_url, border=2)  
    buf = io.BytesIO()  
    img.save(buf)  
    buf.seek(0)  
    return Response(buf, mimetype='image/png')  
  
  
@app.route('/dashboard')  
@login_required  
def personal_dashboard():  
    """ Goes to either the parent's dashboard or child's dashboard. """  
    if current_user.role == 'parent':  
        family_members = list(users_collection.find({'family_id': current_user.family_id}))  
        member_map = {str(m['_id']): m['username'] for m in family_members}  
  
        events = list(events_collection.find({  
            'family_id': current_user.family_id,  
            'status': {'$in': ['completed', 'approved']}  
        }).sort('due_date', DESCENDING).limit(20))  
  
        reward_requests_cursor = rewards_collection.find({  
            'family_id': current_user.family_id,  
            'status': 'requested'  
        }).sort('_id', -1)  
  
        reward_requests = []  
        for r in reward_requests_cursor:  
            r['requested_by_username'] = member_map.get(str(r.get('requested_by_id')), 'Unknown')  
            reward_requests.append(r)  
  
        spend_tx = list(transactions_collection.find({  
            'family_id': current_user.family_id  
        }).sort('spent_at', DESCENDING))  
  
        for t in spend_tx:  
            delta = datetime.utcnow() - t['spent_at']  
            if delta.days > 0:  
                t['spent_at_pretty'] = f"{delta.days}d ago"  
            elif delta.seconds > 3600:  
                t['spent_at_pretty'] = f"{delta.seconds // 3600}h ago"  
            else:  
                t['spent_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"  
  
        return render_template(  
            'index.html',  
            page='dashboard_parent',  
            family_members=family_members,  
            events=events,  
            reward_requests=reward_requests,  
            member_map=member_map,  
            spend_history=spend_tx  
        )  
  
    else:  # Child  
        today = datetime.utcnow().date()  
        events_cursor = events_collection.find({  
            'assigned_to': current_user.id,  
            'status': {'$in': ['assigned', 'completed', 'approved']}  
        }).sort('due_date', ASCENDING)  
  
        child_events = []  
        for e in events_cursor:  
            if e['type'] == 'habit':  
                last_check = e.get('last_completed')  
                e['can_checkin'] = not (last_check and last_check.date() == today)  
            child_events.append(e)  
  
        now = datetime.utcnow()  
        child_rewards = list(rewards_collection.find({  
            'requested_by_id': current_user.id  
        }))  
  
        for reward in child_rewards:  
            if reward.get('status') in ['approved', 'rejected'] and reward.get('resolved_at'):  
                delta = now - reward['resolved_at']  
                if delta.days > 0:  
                    reward['resolved_at_pretty'] = f"{delta.days}d ago"  
                elif delta.seconds > 3600:  
                    reward['resolved_at_pretty'] = f"{delta.seconds // 3600}h ago"  
                else:  
                    minutes_ago = max(1, delta.seconds // 60)  
                    reward['resolved_at_pretty'] = f"{minutes_ago}m ago"  
  
        return render_template('index.html', page='dashboard_child', events=child_events, rewards=child_rewards)  
  
  
@app.route('/family-dashboard')  
@login_required  
def family_dashboard():  
    """ Family-wide summary dashboard. """  
    fam_id = current_user.family_id  
    family_members = list(users_collection.find({'family_id': fam_id}))  
    member_map = {str(m['_id']): m['username'] for m in family_members}  
    events = list(events_collection.find({'family_id': fam_id}))  
  
    stats = {  
        "completed_this_week": 0,  
        "pending_approval": 0,  
        "total_points_awarded": sum(  
            m.get('lifetime_points', 0) for m in family_members if m.get('role') == 'child'  
        ),  
        "weekly_completion_data": {"labels": [], "data": []}  
    }  
  
    today = datetime.utcnow()  
    one_week_ago = today - timedelta(days=7)  
    # We'll store day-of-week counts  
    day_counts = {(today - timedelta(days=i)).strftime('%a'): 0 for i in range(7)}  
  
    for e in events:  
        if e.get('status') == 'completed':  
            stats['pending_approval'] += 1  
        if e.get('status') == 'approved' and e.get('approved_at'):  
            if e['approved_at'] > one_week_ago:  
                stats['completed_this_week'] += 1  
                day_label = e['approved_at'].strftime('%a')  
                if day_label in day_counts:  
                    day_counts[day_label] += 1  
  
    # Build the chart data from newest to oldest day  
    stats['weekly_completion_data']['labels'] = list(day_counts.keys())[::-1]  
    stats['weekly_completion_data']['data'] = list(day_counts.values())[::-1]  
  
    rec_cursor = events_collection.find({  
        'family_id': fam_id,  
        'status': 'approved'  
    }).sort('approved_at', DESCENDING).limit(5)  
  
    recent_events = []  
    for ev in rec_cursor:  
        ev['assigned_to_username'] = member_map.get(str(ev.get('assigned_to')), 'Unknown')  
        if ev.get('approved_at'):  
            delta = datetime.utcnow() - ev['approved_at']  
            if delta.days > 0:  
                ev['approved_at_pretty'] = f"{delta.days}d ago"  
            elif delta.seconds > 3600:  
                ev['approved_at_pretty'] = f"{delta.seconds // 3600}h ago"  
            else:  
                ev['approved_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"  
        else:  
            ev['approved_at_pretty'] = 'Recently'  
        recent_events.append(ev)  
  
    return render_template(  
        'index.html',  
        page='family_dashboard',  
        stats=stats,  
        family_members=family_members,  
        recent_events=recent_events  
    )  
  
  
@app.route('/calendar-focus')  
@login_required  
def calendar_focus():  
    """ Big month/week/day calendar for the entire family. """  
    family_members = list(users_collection.find({'family_id': current_user.family_id}))  
    return render_template('index.html', page='calendar_focus', family_members=family_members)  
  
  
# --- Mood Dashboards ---  
@app.route('/mood-dashboard/personal')  
@login_required  
def mood_dashboard_personal():  
    return render_template('index.html', page='mood_dashboard_personal', mood_config=MOOD_CONFIG)  
  
@app.route('/mood-dashboard/family')  
@login_required  
def mood_dashboard_family():  
    return render_template('index.html', page='mood_dashboard_family', mood_config=MOOD_CONFIG)  
  
  
# --- Family Management ---  
@app.route('/child/edit/<child_id>', methods=['POST'])  
@login_required  
def edit_child(child_id):  
    if current_user.role != 'parent':  
        flash('You do not have permission to do this.', 'error')  
        return redirect(url_for('family_dashboard'))  
  
    child = users_collection.find_one({'_id': ObjectId(child_id), 'family_id': current_user.family_id})  
    if not child:  
        flash('Child not found in your family.', 'error')  
        return redirect(url_for('personal_dashboard'))  
  
    update_data = {}  
    new_username = request.form.get('username')  
    new_password = request.form.get('password')  
  
    if new_username and new_username != child.get('username'):  
        # check if it's taken by another child in the same family  
        if users_collection.find_one({  
            'username': new_username,  
            'family_id': current_user.family_id,  
            '_id': {'$ne': ObjectId(child_id)}  
        }):  
            flash('That username is already taken in your family.', 'error')  
            return redirect(url_for('personal_dashboard'))  
        update_data['username'] = new_username  
  
    if new_password:  
        update_data['password_hash'] = bcrypt.generate_password_hash(new_password).decode('utf-8')  
  
    if update_data:  
        users_collection.update_one({'_id': ObjectId(child_id)}, {'$set': update_data})  
        flash('Child information updated successfully.', 'success')  
  
    return redirect(url_for('personal_dashboard'))  
  
  
@app.route('/child/remove/<child_id>')  
@login_required  
def remove_child(child_id):  
    if current_user.role != 'parent':  
        flash('You do not have permission to do this.', 'error')  
        return redirect(url_for('family_dashboard'))  
  
    child = users_collection.find_one({  
        '_id': ObjectId(child_id),  
        'family_id': current_user.family_id,  
        'role': 'child'  
    })  
    if child:  
        users_collection.delete_one({'_id': ObjectId(child_id)})  
        events_collection.delete_many({'assigned_to': child_id})  
        rewards_collection.delete_many({'requested_by_id': child_id})  
        transactions_collection.delete_many({'child_id': child_id})  
        moods_collection.delete_many({'user_id': ObjectId(child_id)})  
        flash(f"{child.get('username')} has been removed from the family.", 'success')  
    else:  
        flash('Could not find the specified child in your family.', 'error')  
  
    return redirect(url_for('personal_dashboard'))  
  
  
# --- Event (Chore/Habit) Management ---  
@app.route('/event/create', methods=['POST'])  
@login_required  
def create_event():  
    if current_user.role == 'parent':  
        d = datetime.strptime(request.form['due_date'], '%Y-%m-%d')  
        t = request.form['type']  
        doc = {  
            'name': request.form['name'],  
            'description': request.form['description'],  
            'points': int(request.form['points']),  
            'type': t,  
            'family_id': current_user.family_id,  
            'status': 'assigned',  
            'created_at': datetime.utcnow(),  
            'assigned_to': request.form['assigned_to'],  
            'due_date': d  
        }  
        if t == 'habit':  
            doc['streak'] = 0  
            doc['last_completed'] = None  
  
        events_collection.insert_one(doc)  
        flash(f"{t.capitalize()} created and assigned!", 'success')  
    return redirect(url_for('personal_dashboard'))  
  
  
@app.route('/event/complete/<event_id>')  
@login_required  
def complete_event(event_id):  
    """ Child marks a chore as complete => status=completed => parent must approve. """  
    if current_user.role == 'child':  
        events_collection.update_one(  
            {'_id': ObjectId(event_id), 'assigned_to': current_user.id, 'type': 'chore'},  
            {'$set': {'status': 'completed'}}  
        )  
        flash('Chore marked as complete! Awaiting approval.', 'success')  
    return redirect(url_for('personal_dashboard'))  
  
  
@app.route('/event/habit/checkin/<event_id>')  
@login_required  
def checkin_habit(event_id):  
    """ Child 'check in' to a habit once a day => increment streak + points. """  
    if current_user.role == 'child':  
        habit = events_collection.find_one({'_id': ObjectId(event_id), 'assigned_to': current_user.id})  
        if not habit:  
            return redirect(url_for('personal_dashboard'))  
  
        today = datetime.utcnow().date()  
        yesterday = today - timedelta(days=1)  
        last_completed = habit.get('last_completed')  
        curr_streak = habit.get('streak', 0)  
        if last_completed and last_completed.date() == today:  
            flash('You have already checked in for this habit today.', 'error')  
            return redirect(url_for('personal_dashboard'))  
  
        new_streak = curr_streak + 1 if (last_completed and last_completed.date() == yesterday) else 1  
        events_collection.update_one(  
            {'_id': ObjectId(event_id)},  
            {'$set': {  
                'last_completed': datetime.utcnow(),  
                'streak': new_streak  
            }}  
        )  
        users_collection.update_one(  
            {'_id': ObjectId(current_user.id)},  
            {'$inc': {  
                'points': habit['points'],  
                'lifetime_points': habit['points']  
            }}  
        )  
        flash(f"Habit checked in! You earned {habit['points']} points. Streak is now {new_streak}.", 'success')  
    return redirect(url_for('personal_dashboard'))  
  
  
@app.route('/event/approve/<event_id>')  
@login_required  
def approve_event(event_id):  
    """ Parent approves a completed chore => child is awarded points. """  
    if current_user.role == 'parent':  
        e = events_collection.find_one_and_update(  
            {'_id': ObjectId(event_id), 'family_id': current_user.family_id},  
            {'$set': {'status': 'approved', 'approved_at': datetime.utcnow()}}  
        )  
        if e and e.get('assigned_to'):  
            users_collection.update_one(  
                {'_id': ObjectId(e['assigned_to'])},  
                {'$inc': {'points': e['points'], 'lifetime_points': e['points']}}  
            )  
            flash(f"Task approved! {e['points']} points awarded.", 'success')  
    return redirect(url_for('personal_dashboard'))  
  
  
# --- Reward System ---  
@app.route('/reward/request', methods=['POST'])  
@login_required  
def request_reward():  
    """ Child requests a reward => deduct cost => awaits parent approval. """  
    if current_user.role == 'child':  
        cost = int(request.form['points_cost'])  
        user = users_collection.find_one({'_id': ObjectId(current_user.id)})  
        if user.get('points', 0) < cost:  
            flash("You don't have enough available points for that reward!", 'error')  
            return redirect(url_for('personal_dashboard'))  
  
        users_collection.update_one(  
            {'_id': ObjectId(current_user.id)},  
            {'$inc': {'points': -cost}}  
        )  
        reward_id = rewards_collection.insert_one({  
            'name': request.form['name'],  
            'points_cost': cost,  
            'family_id': current_user.family_id,  
            'requested_by_id': current_user.id,  
            'status': 'requested',  
            'resolved_at': None  
        }).inserted_id  
  
        transactions_collection.insert_one({  
            'reward_id': reward_id,  
            'family_id': current_user.family_id,  
            'child_id': current_user.id,  
            'child_username': current_user.username,  
            'reward_name': request.form['name'],  
            'points_spent': cost,  
            'status': 'pending',  
            'spent_at': datetime.utcnow(),  
            'resolved_at': None  
        })  
        flash('Reward requested! Points have been deducted; waiting on parent approval.', 'success')  
  
    return redirect(url_for('personal_dashboard'))  
  
  
@app.route('/reward/handle/<reward_id>/<action>')  
@login_required  
def handle_reward(reward_id, action):  
    """ Parent approves or rejects child reward. """  
    if current_user.role == 'parent':  
        reward = rewards_collection.find_one({'_id': ObjectId(reward_id), 'family_id': current_user.family_id})  
        if not reward:  
            return redirect(url_for('personal_dashboard'))  
  
        if action == 'approve':  
            rewards_collection.update_one(  
                {'_id': reward['_id']},  
                {'$set': {'status': 'approved', 'resolved_at': datetime.utcnow()}}  
            )  
            transactions_collection.update_one(  
                {'reward_id': reward['_id']},  
                {'$set': {'status': 'approved', 'resolved_at': datetime.utcnow()}}  
            )  
            flash("Reward approved!", 'success')  
  
        elif action == 'reject':  
            # refund child's points  
            users_collection.update_one(  
                {'_id': ObjectId(reward['requested_by_id'])},  
                {'$inc': {'points': reward['points_cost']}}  
            )  
            rewards_collection.update_one(  
                {'_id': reward['_id']},  
                {'$set': {'status': 'rejected', 'resolved_at': datetime.utcnow()}}  
            )  
            transactions_collection.update_one(  
                {'reward_id': reward['_id']},  
                {'$set': {'status': 'rejected', 'resolved_at': datetime.utcnow()}}  
            )  
            flash("Reward rejected. Points were refunded.", 'success')  
  
    return redirect(url_for('personal_dashboard'))  
  
  
# --- API Routes ---  
@app.route('/api/events')  
@login_required  
def api_events():  
    """ Return family events in a JSON format for FullCalendar. """  
    fam_id = current_user.family_id  
    fam_members = list(users_collection.find({'family_id': fam_id}))  
    member_map = {str(m['_id']): m['username'] for m in fam_members}  
    query = {'family_id': fam_id}  
  
    if (search := request.args.get('search')):  
        query['name'] = regex.Regex(search, 'i')  
    if (member_id := request.args.get('member')):  
        query['assigned_to'] = member_id  
    if (etype := request.args.get('type')):  
        query['type'] = etype  
  
    cursor = events_collection.find(query)  
    type_colors = {'chore': '#a855f7', 'habit': '#ec4899'}  
    calendar_events = []  
    for e in cursor:  
        calendar_events.append({  
            'title': e['name'],  
            'start': e['due_date'].isoformat(),  
            'allDay': True,  
            'color': type_colors.get(e['type'], '#6b7280'),  
            'extendedProps': {  
                'type': e.get('type'),  
                'description': e.get('description', 'No description.'),  
                'points': e.get('points'),  
                'status': e.get('status'),  
                'assignee_name': member_map.get(e.get('assigned_to'), 'N/A')  
            }  
        })  
  
    return jsonify(calendar_events)  
  
  
@app.route('/api/mood/log', methods=['POST'])  
@login_required  
def api_mood_log():  
    """ Endpoint to log or update a single mood entry. """  
    data = request.json  
    try:  
        entry_date = datetime.strptime(data['date'], '%Y-%m-%d')  
        period = data['period']  
        mood_emoji = data['emoji']  
        note = data.get('note', '')  
        mood_score = MOOD_EMOJI_TO_SCORE.get(mood_emoji)  
  
        if not all([entry_date, period, mood_emoji, mood_score is not None]):  
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400  
  
        moods_collection.update_one(  
            {'user_id': ObjectId(current_user.id), 'date': entry_date, 'period': period},  
            {'$set': {  
                'mood_emoji': mood_emoji,  
                'mood_score': mood_score,  
                'note': note,  
                'updated_at': datetime.utcnow()  
            },  
             '$setOnInsert': {  
                'family_id': ObjectId(current_user.family_id),  
                'created_at': datetime.utcnow()  
            }},  
            upsert=True  
        )  
        return jsonify({'status': 'success'})  
  
    except Exception as e:  
        return jsonify({'status': 'error', 'message': str(e)}), 500  
  
  
@app.route('/api/mood/personal')  
@login_required  
def api_mood_personal():  
    """  
    If 'date' and 'period' are provided, return that single entry;  
    otherwise, return last 30 days for personal mood chart.  
    """  
    if 'date' in request.args and 'period' in request.args:  
        try:  
            entry_date = datetime.strptime(request.args['date'], '%Y-%m-%d')  
            period = request.args['period']  
            entry = moods_collection.find_one({  
                'user_id': ObjectId(current_user.id),  
                'date': entry_date,  
                'period': period  
            })  
            if entry:  
                return jsonify(entry)  
            else:  
                return jsonify({'error': 'Not found'}), 404  
        except Exception as e:  
            return jsonify({'error': str(e)}), 400  
  
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)  
    mood_entries = list(moods_collection.find({  
        'user_id': ObjectId(current_user.id),  
        'date': {'$gte': thirty_days_ago}  
    }).sort('date', ASCENDING))  
  
    labels = [f"{e['date'].strftime('%b %d')} {e['period']}" for e in mood_entries]  
    data = [e['mood_score'] for e in mood_entries]  
    return jsonify({'labels': labels, 'data': data})  
  
  
@app.route('/api/mood/family')  
@login_required  
def api_mood_family():  
    """ Family-level mood distribution & daily averages (last 30 days). """  
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)  
    pipeline_avg = [  
        {'$match': {'family_id': ObjectId(current_user.family_id), 'date': {'$gte': thirty_days_ago}}},  
        {'$group': {'_id': '$date', 'avgScore': {'$avg': '$mood_score'}}},  
        {'$sort': {'_id': 1}}  
    ]  
    daily_avg_data = list(moods_collection.aggregate(pipeline_avg))  
  
    pipeline_dist = [  
        {'$match': {'family_id': ObjectId(current_user.family_id), 'date': {'$gte': thirty_days_ago}}},  
        {'$group': {'_id': '$mood_emoji', 'count': {'$sum': 1}}},  
        {'$sort': {'count': -1}}  
    ]  
    dist_data = list(moods_collection.aggregate(pipeline_dist))  
  
    mood_map = {m['emoji']: m for m in MOOD_CONFIG['moods']}  
  
    return jsonify({  
        'daily_average': {  
            'labels': [d['_id'].strftime('%b %d') for d in daily_avg_data],  
            'data': [round(d['avgScore'], 2) for d in daily_avg_data]  
        },  
        'distribution': {  
            'labels': [  
                f"{d['_id']} ({mood_map.get(d['_id'], {}).get('desc', '')})"  
                for d in dist_data  
            ],  
            'data': [d['count'] for d in dist_data],  
            'colors': [mood_map.get(d['_id'], {}).get('color', '#cccccc') for d in dist_data]  
        }  
    })  
  
  
@app.route('/api/consult-ai', methods=['POST'])  
@login_required  
def api_consult_ai():  
    """  
    Example: Pass the user's CSV mood data to an external AI service   
    and get back supportive insights. (Mock route)  
    """  
    history = list(moods_collection.find(  
        {'user_id': ObjectId(current_user.id)},  
        {'date': 1, 'period': 1, 'mood_emoji': 1, 'note': 1, '_id': 0}  
    ).sort('date', ASCENDING))  
  
    if len(history) < 2:  
        return jsonify({'error': "Not enough data. Please log at least two moods to get insights."}), 400  
  
    output = io.StringIO()  
    writer = csv.DictWriter(output, fieldnames=['date', 'period', 'mood', 'note'])  
    writer.writeheader()  
    for row in history:  
        writer.writerow({  
            'date': row['date'].strftime('%Y-%m-%d'),  
            'period': row['period'],  
            'mood': row['mood_emoji'],  
            'note': row.get('note', '')  
        })  
  
    csv_content = output.getvalue()  
    payload = {  
        "context": [{  
            "text": f"Analyze the following mood data in CSV format:\n{csv_content}",  
            "url": "user-mood-insights"  
        }],  
        "user_input": (  
            "Provide a brief, supportive analysis of my mood patterns based on this data, "  
            "grounded in CBT principles. Format your response with markdown for readability, "  
            "using double asterisks for bolding."  
        )  
    }  
  
    try:  
        import requests  
        response = requests.post(MOOD_CONFIG['aiApiUrl'], json=payload, timeout=45)  
        response.raise_for_status()  
        data = response.json()  
        return jsonify({'ai_response': data.get('ai_response', 'No response from AI.')})  
    except requests.exceptions.RequestException as e:  
        return jsonify({'error': f"Failed to connect to AI service: {e}"}), 503  
    except Exception as e:  
        return jsonify({'error': str(e)}), 500  
  
  
@app.route('/api/generic-ai', methods=['POST'])  
@login_required  
def generic_ai_call():  
    """  
    Another example for a generic AI call.   
    In a real setup you'd connect to your AI service with the provided context.  
    """  
    user_context = request.json.get('text', '').strip()  
    user_input = request.json.get('user_input', '').strip()  
    if not user_context or not user_input:  
        return jsonify({'error': 'Both "text" and "user_input" fields are required.'}), 400  
  
    payload = {  
        "context": user_context,  
        "user_input": user_input  
    }  
    try:  
        import requests  
        response = requests.post(MOOD_CONFIG['aiApiUrl'], json=payload, timeout=45)  
        response.raise_for_status()  
        data = response.json()  
        return jsonify({'ai_response': data.get('ai_response', 'No response from AI.')})  
    except requests.exceptions.RequestException as e:  
        return jsonify({'error': f"Failed to connect to AI service: {e}"}), 503  
    except Exception as e:  
        return jsonify({'error': str(e)}), 500  
  
  
@app.route('/share_invite')  
@login_required  
def share_invite():  
    """ Return a #hash-based invite link for client usage. """  
    if current_user.role != 'parent':  
        return jsonify({"error": "Not authorized"}), 403  
    shareable_link_with_hash = f"{BASE_URL}/#invite={current_user.id}"  
    return jsonify({"shareable_link": shareable_link_with_hash})  
  
  
if __name__ == '__main__':  
    # Important: in production, use gunicorn or another WSGI server, not app.run(debug=True).  
    app.run(debug=True, port=5001)  
  
"""  
gunicorn --workers 3 --bind 0.0.0.0:$PORT app:app  
gunicorn --workers 3 --bind 0.0.0.0:5001 app:app  
"""