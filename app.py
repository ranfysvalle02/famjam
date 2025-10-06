import os
import io
import json
import csv
import itertools
import qrcode
from datetime import datetime, timedelta, date, timezone
from collections import defaultdict
import pytz  # Import timezone library

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    Response,
    jsonify
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)
from flask_bcrypt import Bcrypt
from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne
from bson.objectid import ObjectId
from bson import json_util, regex
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

# Optional: For OpenAI usage
import openai  # If using the official OpenAI library

################################################################################
# 1. ENVIRONMENT & FLASK APP CONFIGURATION
################################################################################
load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a-super-secret-key-that-you-should-change')

# --- TIMEZONE CONFIGURATION ---
TIMEZONE_NAME = 'America/New_York'
TIMEZONE = pytz.timezone(TIMEZONE_NAME)

def now_est():
    """Returns the current time localized to America/New_York (EST/EDT)."""
    return datetime.now(TIMEZONE)

def today_est():
    """Returns today's date based on America/New_York (EST/EDT)."""
    return now_est().date()

# Helper to create a timezone-aware midnight datetime
def start_of_day_est(dt_date):
    """Returns a timezone-aware datetime representing midnight EST for the given date object."""
    dt_naive = datetime.combine(dt_date, datetime.min.time())
    # Localize the naive datetime to the desired timezone
    return TIMEZONE.localize(dt_naive)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
else:
    openai_client = None

################################################################################
# 2. MONGODB SETUP
################################################################################
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
BASE_URL = os.environ.get('BASE_URL', 'https://famjam.oblivio-company.com')
client = MongoClient(MONGO_URI)
db = client['mchores_app']

# MONGODB COLLECTIONS
users_collection = db['users']
events_collection = db['events']
rewards_collection = db['rewards'] # For reward requests/history
transactions_collection = db['transactions']
moods_collection = db['moods']
famjam_plans_collection = db['famjam_plans']
timers_collection = db['timers']
notes_collection = db['notes']
personal_todos_collection = db['personal_todos']
challenges_collection = db['challenges']
direct_messages_collection = db['direct_messages']
families_collection = db['families']

# NEW: Collection for the parent-managed reward store
store_rewards_collection = db['store_rewards']

################################################################################
# 3. RECOMMENDED INDEXES
################################################################################
users_collection.create_index([('email', ASCENDING)], unique=True, sparse=True)
users_collection.create_index([('username', ASCENDING), ('family_id', ASCENDING)], unique=True, sparse=True)
events_collection.create_index([('family_id', ASCENDING), ('due_date', ASCENDING)])
events_collection.create_index(
    [('family_id', ASCENDING), ('name', ASCENDING), ('due_date', ASCENDING), ('assigned_to', ASCENDING)],
    unique=True
)
moods_collection.create_index([('user_id', ASCENDING), ('date', ASCENDING), ('period', ASCENDING)], unique=True)
moods_collection.create_index([('family_id', ASCENDING), ('date', ASCENDING)])
famjam_plans_collection.create_index([('family_id', ASCENDING), ('status', ASCENDING)])
timers_collection.create_index([('family_id', ASCENDING), ('end_date', ASCENDING)])
notes_collection.create_index([('user_id', ASCENDING)])
personal_todos_collection.create_index([('user_id', ASCENDING)])
challenges_collection.create_index([('family_id', ASCENDING), ('status', ASCENDING)])
direct_messages_collection.create_index([('family_id', ASCENDING), ('sent_at', DESCENDING)])
store_rewards_collection.create_index([('family_id', ASCENDING)])

################################################################################
# 4. BCRYPT, LOGIN MANAGER, AND MODELS
################################################################################
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

MOOD_CONFIG = {
    'moods': [
        {'emoji': '😖', 'desc': 'Upset', 'score': 1, 'color': '#ef4444'},
        {'emoji': '😔', 'desc': 'Not Happy', 'score': 2, 'color': '#f97316'},
        {'emoji': '😌', 'desc': 'Calm / Okay', 'score': 3, 'color': '#84cc16'},
        {'emoji': '😎', 'desc': 'Very Happy', 'score': 4, 'color': '#22c55e'}
    ]
}
MOOD_EMOJI_TO_SCORE = {m['emoji']: m['score'] for m in MOOD_CONFIG['moods']}

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.email = user_data.get('email')
        self.username = user_data.get('username')
        self.password_hash = user_data['password_hash']
        self.role = user_data['role']
        self.family_id = user_data.get('family_id')
        self.points = user_data.get('points', 0)
        self.lifetime_points = user_data.get('lifetime_points', 0)

    @staticmethod
    def get(user_id):
        try:
            data = users_collection.find_one({'_id': ObjectId(user_id)})
            if data and data.get('role') in ['parent', 'child']:
                return User(data)
        except:
            return None
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

class MongoJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (ObjectId, datetime, date)):
            return str(obj)
        return json_util.default(obj)

app.json_encoder = MongoJsonEncoder

################################################################################
# 5. BASIC / AUTH ROUTES
################################################################################
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('personal_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('personal_dashboard'))

    if request.method == 'POST':
        identifier = request.form['email_or_username']
        user_data = users_collection.find_one({'$or': [{'email': identifier}, {'username': identifier}]})
        if user_data and bcrypt.check_password_hash(user_data['password_hash'], request.form['password']):
            login_user(User(user_data))
            return redirect(url_for('personal_dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'error')
    return render_template('index.html', page='login')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/terms')
def terms_of_service():
    return render_template('terms.html')

@app.route('/privacy')
def privacy_policy():
    return render_template('privacy.html')

@app.route('/join/<invite_code>')
def join_family(invite_code):
    try:
        family = families_collection.find_one({'_id': ObjectId(invite_code)})
        if not family:
            flash('This is not a valid invite code.', 'error')
            return redirect(url_for('login'))
    except:
        flash('Invalid invite code format.', 'error')
        return redirect(url_for('login'))

    first_parent_id = family.get('parent_ids', [None])[0]
    parent = users_collection.find_one({'_id': first_parent_id})
    parent_name = parent.get('username', 'your family organizer') if parent else 'your family organizer'

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

        family_doc = {'name': f"{username}'s Family", 'parent_ids': [], 'created_at': now_est()}
        family_id = families_collection.insert_one(family_doc).inserted_id
        family_id_str = str(family_id)

        new_id = users_collection.insert_one({
            'email': email, 'username': username, 'password_hash': hashed_pw,
            'role': 'parent', 'family_id': family_id_str,
            'lifetime_points': 0, 'points': 0
        }).inserted_id

        families_collection.update_one({'_id': family_id}, {'$push': {'parent_ids': new_id}})

        flash('Parent account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('index.html', page='register_parent')

@app.route('/register/parent/<family_id>', methods=['GET', 'POST'])
def register_secondary_parent(family_id):
    try:
        family = families_collection.find_one({'_id': ObjectId(family_id)})
        if not family:
            flash('This is not a valid family invite code.', 'error')
            return redirect(url_for('login'))
    except:
        flash('Invalid invite code format.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']

        if users_collection.find_one({'$or': [{'email': email}, {'username': username, 'family_id': family_id}]}):
            flash('Email or username already in use in this family.', 'error')
            return redirect(url_for('register_secondary_parent', family_id=family_id))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_parent_id = users_collection.insert_one({
            'email': email, 'username': username, 'password_hash': hashed_pw,
            'role': 'parent', 'family_id': family_id,
            'lifetime_points': 0, 'points': 0
        }).inserted_id

        families_collection.update_one({'_id': ObjectId(family_id)}, {'$push': {'parent_ids': new_parent_id}})

        flash(f'Welcome to {family.get("name", "the family")}! Please log in.', 'success')
        return redirect(url_for('login'))

    family_name = family.get('name', 'Family')
    return render_template('index.html', page='register_parent', family_id=family_id, family_name=family_name)

@app.route('/join')
@login_required
def invite():
    if current_user.role != 'parent':
        return redirect(url_for('personal_dashboard'))
    invite_url = f"{BASE_URL}{url_for('join_family', invite_code=current_user.family_id)}"
    return render_template('index.html', page='invite', invite_url=invite_url)

@app.route('/qr_code')
@login_required
def qr_code():
    if current_user.role != 'parent':
        return Response(status=403)
    invite_url = f"{BASE_URL}{url_for('join_family', invite_code=current_user.family_id)}"
    img = qrcode.make(invite_url, border=2)
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return Response(buf, mimetype='image/png')

@app.route('/register/child/<invite_code>', methods=['GET', 'POST'])
def register_child(invite_code):
    try:
        family = families_collection.find_one({'_id': ObjectId(invite_code)})
        if not family:
            flash('Invalid invite code.', 'error')
            return redirect(url_for('login'))
    except:
        flash('Invalid invite code format.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if users_collection.find_one({'username': username, 'family_id': invite_code}):
            flash('Username already taken in this family.', 'error')
            return redirect(url_for('register_child', invite_code=invite_code))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        users_collection.insert_one({
            'username': username, 'password_hash': hashed_pw, 'role': 'child',
            'family_id': invite_code, 'points': 0, 'lifetime_points': 0
        })
        flash('Child account created! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('index.html', page='register_child', invite_code=invite_code)

################################################################################
# 6. UNIFIED DASHBOARD ROUTES
################################################################################

def get_formatted_events(family_oid, member_map, filters={}):
    query = {'family_id': family_oid}
    query.update(filters)
    child_colors = ['#ef4444', '#f97316', '#eab308', '#84cc16', '#22c55e', '#14b8a6', '#06b6d4', '#6366f1', '#a855f7']
    child_member_ids = [uid for uid, uname in member_map.items() if users_collection.find_one({'_id': ObjectId(uid), 'role': 'child'})]
    child_color_map = {child_id: child_colors[i % len(child_colors)] for i, child_id in enumerate(child_member_ids)}
    default_color = '#6b7280'
    formatted_events = []
    events_cursor = events_collection.find(query).sort([('due_date', ASCENDING), ('name', ASCENDING)])

    for event in events_cursor:
        assignee_id_str = str(event.get('assigned_to'))
        can_checkin = False
        if event.get('type') == 'habit':
            last_completed = event.get('last_completed')
            last_completed_date_est = last_completed.astimezone(TIMEZONE).date() if last_completed else None
            if not (last_completed_date_est and last_completed_date_est == today_est()):
                can_checkin = True

        formatted_events.append({
            '_id': str(event['_id']),
            'name': event.get('name'),
            'description': event.get('description'),
            'points': event.get('points'),
            'type': event.get('type'),
            'status': event.get('status'),
            'streak': event.get('streak', 0),
            'assignee_name': member_map.get(assignee_id_str, 'N/A'),
            'assignee_id': assignee_id_str,
            'color': child_color_map.get(assignee_id_str, default_color),
            'can_checkin': can_checkin,
            'due_date': event.get('due_date')
        })
    return formatted_events

@app.route('/dashboard')
@login_required
def personal_dashboard():
    family_oid = ObjectId(current_user.family_id)
    today = today_est()

    # --- PARENT DASHBOARD LOGIC (NEW & ROBUST) ---
    if current_user.role == 'parent':
        # --- Basic Setup ---
        family_members_cursor = users_collection.find({'family_id': current_user.family_id})
        family_members = list(family_members_cursor)
        member_map = {str(m['_id']): m['username'] for m in family_members}
        for member in family_members:
            member['_id'] = str(member['_id'])

        # --- Weekly Stats Calculation ---
        now = now_est()
        start_of_week = start_of_day_est(today - timedelta(days=now.weekday()))
        end_of_week = start_of_week + timedelta(days=7)

        weekly_stats = {
            'total_points_assigned': 0,
            'child_stats': defaultdict(lambda: {'tasks_assigned': 0, 'points_assigned': 0})
        }
        tasks_this_week_cursor = events_collection.find({
            'family_id': family_oid,
            'due_date': {'$gte': start_of_week, '$lt': end_of_week}
        })

        for task in tasks_this_week_cursor:
            weekly_stats['total_points_assigned'] += task.get('points', 0)
            child_id = str(task.get('assigned_to'))
            if child_id in member_map:
                weekly_stats['child_stats'][child_id]['tasks_assigned'] += 1
                weekly_stats['child_stats'][child_id]['points_assigned'] += task.get('points', 0)
        
        # --- Pending Approvals ---
        pending_events = list(events_collection.find({
            'family_id': family_oid,
            'status': 'completed'
        }).sort('completed_at', DESCENDING))

        # --- Mood Tracking Activity ---
        start_of_today = start_of_day_est(today)
        mood_trackers_today_cursor = moods_collection.find({
            'family_id': family_oid,
            'date': start_of_today
        })
        mood_trackers_today = {str(mood['user_id']) for mood in mood_trackers_today_cursor}

        # --- Reward Store Management ---
        available_rewards = list(store_rewards_collection.find({'family_id': family_oid}).sort('cost', ASCENDING))
        
        # ✨ NEW: Fetch Pending Reward Requests
        pending_rewards = list(rewards_collection.find({
            'status': 'pending',
        }).sort('requested_at', DESCENDING))
        
        # ✨ NEW: Create a map of user IDs to usernames for the reward requests
        user_ids_for_rewards = [r['requested_by_id'] for r in pending_rewards]
        users_for_rewards = {str(u['_id']): u['username'] for u in users_collection.find({'_id': {'$in': user_ids_for_rewards}})}
        
        for reward_req in pending_rewards:
            reward_req['username'] = users_for_rewards.get(str(reward_req.get('requested_by_id')), 'Unknown')
            
        return render_template(
            'index.html',
            page='dashboard_parent',
            family_members=family_members,
            member_map=member_map,
            pending_events=pending_events,
            pending_rewards=pending_rewards, # ✨ NEW: Pass data to template
            weekly_stats=weekly_stats,
            mood_trackers_today=mood_trackers_today,
            available_rewards=available_rewards,
            TIMEZONE=TIMEZONE
        )

    # --- CHILD DASHBOARD LOGIC ---
    else: # current_user.role == 'child'
        current_user_oid = ObjectId(current_user.id)
        
        family_doc = families_collection.find_one({'_id': family_oid})
        parent = {}
        if family_doc and family_doc.get('parent_ids'):
            parent_doc = users_collection.find_one({'_id': family_doc['parent_ids'][0]})
            if parent_doc:
                parent['_id'] = str(parent_doc['_id'])
                parent['username'] = parent_doc.get('username')

        start_of_today_naive = datetime.combine(today, datetime.min.time())
        end_of_today_naive = start_of_today_naive + timedelta(days=1)
        start_of_today_utc = start_of_day_est(today).astimezone(timezone.utc)

        overdue_events = list(events_collection.find({
            'assigned_to': current_user_oid, 'type': 'chore',
            'status': 'assigned', 'due_date': {'$lt': start_of_today_utc}
        }).sort('due_date', ASCENDING))

        todays_events_cursor = events_collection.find({
            'assigned_to': current_user_oid,
            'due_date': {'$gte': start_of_today_naive, '$lt': end_of_today_naive}
        }).sort('type', DESCENDING)

        todays_events = []
        for event in todays_events_cursor:
            event['can_checkin'] = False
            if event.get('type') == 'habit':
                last_completed = event.get('last_completed')
                last_completed_date = last_completed.astimezone(TIMEZONE).date() if last_completed else None
                if not (last_completed_date and last_completed_date == today):
                    event['can_checkin'] = True
            todays_events.append(event)
        
        available_rewards = list(store_rewards_collection.find({'family_id': family_oid}).sort('cost', ASCENDING))
        rewards = list(rewards_collection.find({'requested_by_id': current_user_oid}))
        now = now_est()
        for r in rewards:
            if r.get('resolved_at'):
                delta = now - r['resolved_at'].astimezone(TIMEZONE)
                if delta.days > 0: r['resolved_at_pretty'] = f"{delta.days}d ago"
                elif (h := delta.seconds // 3600) > 0: r['resolved_at_pretty'] = f"{h}h ago"
                else: r['resolved_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"

        family_members = list(users_collection.find({'family_id': str(family_oid)}))
        member_map = {str(m['_id']): m['username'] for m in family_members}
        challenges = list(challenges_collection.find({'family_id': family_oid, 'status': {'$in': ['open', 'in_progress', 'completed']}}).sort('created_at', DESCENDING))
        for c in challenges:
            c['claimer_username'] = member_map.get(str(c.get('claimed_by_id')), '')

        return render_template(
            'index.html', page='dashboard_child',
            todays_events=todays_events,
            overdue_events=overdue_events,
            rewards=rewards,
            available_rewards=available_rewards,
            challenges=challenges,
            parent=parent,
            TIMEZONE=TIMEZONE
        )

@app.route('/family-dashboard')
@login_required
def family_dashboard():
    fam_oid = ObjectId(current_user.family_id)
    family_members_cursor = users_collection.find({'family_id': current_user.family_id})
    family_members = list(family_members_cursor)
    member_map = {str(m['_id']): m['username'] for m in family_members}
    for member in family_members: member['_id'] = str(member['_id'])

    child_ids_obj = [m['_id'] for m in family_members if m.get('role') == 'child']

    events = list(events_collection.find({'family_id': fam_oid}))
    stats = {
        "completed_this_week": 0, "pending_approval": 0,
        "total_points_awarded": sum(m.get('lifetime_points', 0) for m in family_members if m.get('role') == 'child'),
        "weekly_completion_data": {"labels": [], "data": []}
    }
    now = now_est()
    one_week_ago = now - timedelta(days=7)
    day_counts = {(now.date() - timedelta(days=i)).strftime('%a'): 0 for i in range(7)}

    for e in events:
        if e.get('status') == 'completed': stats['pending_approval'] += 1
        if e.get('status') == 'approved' and e.get('approved_at'):
            approved_at_aware = e['approved_at'].astimezone(TIMEZONE)
            if approved_at_aware > one_week_ago:
                stats['completed_this_week'] += 1
                day_label = approved_at_aware.strftime('%a')
                if day_label in day_counts:
                    day_counts[day_label] += 1
    
    stats['weekly_completion_data']['labels'] = list(day_counts.keys())[::-1]
    stats['weekly_completion_data']['data'] = list(day_counts.values())[::-1]
    
    rec_cursor = events_collection.find({
        'family_id': fam_oid, 'status': 'approved', 'assigned_to': {'$in': [ObjectId(cid) for cid in child_ids_obj]}
    }).sort('approved_at', DESCENDING).limit(5)
    
    recent_events = []
    for ev in rec_cursor:
        ev['assigned_to_username'] = member_map.get(str(ev.get('assigned_to')), 'Unknown')
        if ev.get('approved_at'):
            delta = now - ev['approved_at'].astimezone(TIMEZONE)
            if delta.days > 0: ev['approved_at_pretty'] = f"{delta.days}d ago"
            elif (h := delta.seconds // 3600) > 0: ev['approved_at_pretty'] = f"{h}h ago"
            else: ev['approved_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"
        recent_events.append(ev)

    timers = []
    for t in timers_collection.find({'family_id': fam_oid}).sort('end_date', ASCENDING):
        end_date_aware = start_of_day_est(t['end_date'].date())
        delta = end_date_aware - now
        time_left = "Timer ended"
        if delta.total_seconds() >= 0:
            if (days_left := delta.days) >= 1: time_left = f"{days_left} day{'s' if days_left != 1 else ''} left"
            else:
                hours, remainder = divmod(delta.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                if hours > 0: time_left = f"{hours} hour{'s' if hours != 1 else ''} left"
                else: time_left = f"{minutes} minute{'s' if minutes != 1 else ''} left"
        timers.append({
            'name': t['name'],
            'end_date': end_date_aware.strftime('%b %d, %Y'),
            'creator_name': member_map.get(str(t.get('created_by')), "Unknown"),
            'time_left': time_left
        })
        
    # ✨ NEW: Fetch rewards for the family hub view
    available_rewards = list(store_rewards_collection.find({'family_id': fam_oid}).sort('cost', ASCENDING))
    
    return render_template(
        'index.html', 
        page='family_dashboard', 
        stats=stats, 
        family_members=family_members, 
        recent_events=recent_events, 
        timers=timers,
        available_rewards=available_rewards  # ✨ NEW: Pass rewards to template
    )

@app.route('/calendar-focus')
@login_required
def calendar_focus():
    family_members = list(users_collection.find({'family_id': current_user.family_id}))
    for member in family_members:
        member['_id'] = str(member['_id'])
    return render_template('index.html', page='calendar_focus', family_members=family_members)

@app.route('/mood-dashboard/personal')
@login_required
def mood_dashboard_personal():
    return render_template('index.html', page='mood_dashboard_personal', mood_config=MOOD_CONFIG)

@app.route('/mood-dashboard/family')
@login_required
def mood_dashboard_family():
    return render_template('index.html', page='mood_dashboard_family', mood_config=MOOD_CONFIG)

################################################################################
# 7. NEW REWARD STORE MANAGEMENT ROUTES
################################################################################
@app.route('/reward/request/resolve/<request_id>', methods=['POST'])
@login_required
def resolve_reward_request(request_id):
    """Allows a parent to approve or deny a reward request."""
    if current_user.role != 'parent':
        flash("You are not authorized to manage rewards.", "error")
        return redirect(url_for('personal_dashboard'))

    action = request.form.get('action') # Should be 'approve' or 'deny'
    reward_request = rewards_collection.find_one({'_id': ObjectId(request_id)})
    
    if not reward_request:
        flash("Reward request not found.", "error")
        return redirect(url_for('personal_dashboard'))

    if action == 'approve':
        rewards_collection.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'approved',
                'resolved_at': now_est(),
                'resolved_by_id': ObjectId(current_user.id)
            }}
        )
        flash(f"Request for '{reward_request['reward_name']}' approved.", "success")

    elif action == 'deny':
        # Refund the points to the child
        users_collection.update_one(
            {'_id': reward_request['requested_by_id']},
            {'$inc': {'points': reward_request['cost']}}
        )
        rewards_collection.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'denied',
                'resolved_at': now_est(),
                'resolved_by_id': ObjectId(current_user.id)
            }}
        )
        flash(f"Request for '{reward_request['reward_name']}' denied. Points have been refunded.", "info")

    return redirect(url_for('personal_dashboard'))
@app.route('/reward/request/<reward_id>', methods=['POST'])
@login_required
def request_reward(reward_id):
    """Allows a child to request a reward from the store using their points."""
    if current_user.role != 'child':
        flash("Only children can request rewards.", "error")
        return redirect(url_for('personal_dashboard'))

    reward = store_rewards_collection.find_one({
        '_id': ObjectId(reward_id),
        'family_id': ObjectId(current_user.family_id)
    })

    if not reward:
        flash("This reward is not available.", "error")
        return redirect(url_for('personal_dashboard'))

    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    if user.get('points', 0) < reward.get('cost', 0):
        flash("You don't have enough points for this reward.", "error")
        return redirect(url_for('personal_dashboard'))

    # Deduct points and log the request
    users_collection.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$inc': {'points': -reward['cost']}}
    )

    rewards_collection.insert_one({
        'requested_by_id': ObjectId(current_user.id),
        'reward_name': reward['name'],
        'cost': reward['cost'],
        'status': 'pending', # Statuses: pending, approved, denied
        'requested_at': now_est(),
        'resolved_at': None,
        'resolved_by_id': None
    })

    flash(f"You've successfully requested '{reward['name']}'! Awaiting parent approval.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/reward/store/add', methods=['POST'])
@login_required
def add_store_reward():
    if current_user.role != 'parent':
        flash("You are not authorized to manage rewards.", "error")
        return redirect(url_for('personal_dashboard'))

    name = request.form.get('name', '').strip()
    cost_str = request.form.get('cost', '')

    if not name or not cost_str:
        flash("Reward name and cost are required.", "error")
        return redirect(url_for('personal_dashboard'))
    
    try:
        cost = int(cost_str)
        if cost <= 0: raise ValueError()
    except ValueError:
        flash("Please enter a valid, positive number for the point cost.", "error")
        return redirect(url_for('personal_dashboard'))

    store_rewards_collection.insert_one({
        'name': name, 'cost': cost,
        'family_id': ObjectId(current_user.family_id),
        'created_at': now_est()
    })
    flash(f"Reward '{name}' added to the store.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/reward/store/delete/<reward_id>')
@login_required
def delete_store_reward(reward_id):
    if current_user.role != 'parent':
        flash("You are not authorized to manage rewards.", "error")
        return redirect(url_for('personal_dashboard'))

    result = store_rewards_collection.delete_one({
        '_id': ObjectId(reward_id),
        'family_id': ObjectId(current_user.family_id)
    })
    if result.deleted_count > 0:
        flash("Reward removed from the store.", "success")
    else:
        flash("Could not find the reward to delete.", "error")
    return redirect(url_for('personal_dashboard'))

################################################################################
# 8. EVENT / TASK & REWARD REQUESTS
################################################################################

@app.route('/event/create', methods=['POST'])
@login_required
def create_event():
    if current_user.role != 'parent':
        flash("You are not authorized to create tasks.", "error")
        return redirect(url_for('personal_dashboard'))

    assigned_to_value = request.form['assigned_to']
    recurrence = request.form['recurrence']
    task_type = request.form['type']
    
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'_id': 1}))
    if not children:
        flash("There are no children in the family to assign tasks to.", "warning")
        return redirect(url_for('personal_dashboard'))
    child_ids = [str(c['_id']) for c in children]

    input_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
    start_date = start_of_day_est(input_date)
    
    family_oid = ObjectId(current_user.family_id)
    all_events_to_insert = []
    
    base_doc_template = {
        'name': request.form['name'], 'description': "", 'points': int(request.form['points']),
        'type': task_type, 'family_id': family_oid, 'status': 'assigned', 'created_at': now_est()
    }
    if task_type == 'habit':
        base_doc_template.update({'streak': 0, 'last_completed': None})

    if recurrence == 'none':
        assignees = child_ids if assigned_to_value == "__ALL__" else [child_ids[0]] if assigned_to_value == "__ROUND_ROBIN__" else [assigned_to_value]
        for user_id in assignees:
            doc = base_doc_template.copy()
            doc['assigned_to'] = ObjectId(user_id)
            doc['due_date'] = start_date
            all_events_to_insert.append(doc)
    else:
        end_date = start_date + timedelta(days=90)
        current_date = start_date
        delta = {'daily': timedelta(days=1), 'weekly': timedelta(weeks=1), 'monthly': relativedelta(months=1)}.get(recurrence)
        if not delta:
            flash("Invalid recurrence type.", "error")
            return redirect(url_for('personal_dashboard'))

        child_cycler = itertools.cycle(child_ids)
        while current_date < end_date:
            assignees = child_ids if assigned_to_value == "__ALL__" else [next(child_cycler)] if assigned_to_value == "__ROUND_ROBIN__" else [assigned_to_value]
            for user_id in assignees:
                doc = base_doc_template.copy()
                doc['assigned_to'] = ObjectId(user_id)
                doc['due_date'] = current_date
                all_events_to_insert.append(doc)
            current_date += delta

    if all_events_to_insert:
        try:
            events_collection.insert_many(all_events_to_insert, ordered=False)
            flash("Task(s) scheduled successfully!", 'success')
        except Exception as e:
            if "E11000 duplicate key error" in str(e):
                flash("Task(s) scheduled. Some duplicates for existing dates were skipped.", 'warning')
            else:
                flash(f"An error occurred: {e}", "error")
    return redirect(url_for('personal_dashboard'))

@app.route('/event/edit/<event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
    if current_user.role != 'parent':
        flash("You are not authorized to edit tasks.", "error")
        return redirect(url_for('personal_dashboard'))
    event = events_collection.find_one({'_id': ObjectId(event_id), 'family_id': ObjectId(current_user.family_id)})
    if not event:
        flash("Task not found.", "error")
        return redirect(url_for('manage_plan'))
    due_date_aware = start_of_day_est(datetime.strptime(request.form['due_date'], '%Y-%m-%d').date())
    update_data = {
        'name': request.form['name'], 'description': request.form['description'],
        'points': int(request.form['points']), 'assigned_to': ObjectId(request.form['assigned_to']),
        'due_date': due_date_aware
    }
    events_collection.update_one({'_id': ObjectId(event_id)}, {'$set': update_data})
    flash("Task has been updated.", "success")
    return redirect(url_for('manage_plan'))

@app.route('/event/delete/<event_id>')
@login_required
def delete_event(event_id):
    if current_user.role != 'parent':
        flash("You are not authorized to delete tasks.", "error")
        return redirect(url_for('personal_dashboard'))
    event_to_delete = events_collection.find_one({'_id': ObjectId(event_id), 'family_id': ObjectId(current_user.family_id)})
    if not event_to_delete:
        flash("Task not found.", "error")
        return redirect(url_for('manage_plan'))
    events_collection.delete_one({'_id': ObjectId(event_id)})
    flash("Task has been deleted.", "success")
    return redirect(url_for('manage_plan'))

@app.route('/event/complete/<event_id>')
@login_required
def complete_event(event_id):
    if current_user.role == 'child':
        events_collection.update_one(
            {'_id': ObjectId(event_id), 'assigned_to': ObjectId(current_user.id), 'type': 'chore'},
            {'$set': {'status': 'completed', 'completed_at': now_est()}}
        )
        flash('Chore marked as complete! Awaiting approval.', 'success')
    return redirect(url_for('personal_dashboard'))

@app.route('/event/habit/checkin/<event_id>')
@login_required
def checkin_habit(event_id):
    if current_user.role == 'child':
        habit = events_collection.find_one({'_id': ObjectId(event_id), 'assigned_to': ObjectId(current_user.id)})
        if not habit:
            return redirect(url_for('personal_dashboard'))
        today = today_est()
        last_completed = habit.get('last_completed')
        last_completed_date_est = last_completed.astimezone(TIMEZONE).date() if last_completed else None
        if last_completed_date_est and last_completed_date_est == today:
            flash('You have already checked in today.', 'error')
            return redirect(url_for('personal_dashboard'))
        new_streak = habit.get('streak', 0) + 1 if (last_completed_date_est and last_completed_date_est == today - timedelta(days=1)) else 1
        events_collection.update_one({'_id': ObjectId(event_id)}, {'$set': {'last_completed': now_est(), 'streak': new_streak}})
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$inc': {'points': habit['points'], 'lifetime_points': habit['points']}}
        )
        flash(f"Habit checked in! You earned {habit['points']} points. Streak is now {new_streak}.", 'success')
    return redirect(url_for('personal_dashboard'))

@app.route('/event/approve/<event_id>')
@login_required
def approve_event(event_id):
    if current_user.role == 'parent':
        e = events_collection.find_one_and_update(
            {'_id': ObjectId(event_id), 'family_id': ObjectId(current_user.family_id)},
            {'$set': {'status': 'approved', 'approved_at': now_est()}}
        )
        if e and e.get('assigned_to'):
            users_collection.update_one(
                {'_id': e['assigned_to']},
                {'$inc': {'points': e['points'], 'lifetime_points': e['points']}}
            )
            flash(f"Task approved! {e['points']} points awarded.", 'success')
    return redirect(url_for('personal_dashboard'))

# ✨ NEW: Bulk approval route
@app.route('/event/bulk_approve', methods=['POST'])
@login_required
def bulk_approve_events():
    if current_user.role != 'parent':
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    event_ids_str = data.get('event_ids', [])
    if not event_ids_str:
        return jsonify({"error": "No event IDs provided"}), 400
    event_ids_obj = [ObjectId(eid) for eid in event_ids_str]
    events_to_approve = list(events_collection.find({
        '_id': {'$in': event_ids_obj}, 'family_id': ObjectId(current_user.family_id), 'status': 'completed'
    }))
    if not events_to_approve:
        return jsonify({"status": "warning", "message": "No valid tasks to approve."}), 200

    points_to_award = defaultdict(int)
    valid_event_ids_to_update = []
    for event in events_to_approve:
        points_to_award[event['assigned_to']] += event.get('points', 0)
        valid_event_ids_to_update.append(event['_id'])

    if points_to_award:
        user_updates = [UpdateOne({'_id': uid}, {'$inc': {'points': pts, 'lifetime_points': pts}}) for uid, pts in points_to_award.items()]
        users_collection.bulk_write(user_updates)

    events_collection.update_many({'_id': {'$in': valid_event_ids_to_update}}, {'$set': {'status': 'approved', 'approved_at': now_est()}})
    flash(f"{len(valid_event_ids_to_update)} task(s) approved!", "success")
    return jsonify({"status": "success", "approved_count": len(valid_event_ids_to_update)}), 200


@app.route('/plan/add_task/<plan_id>', methods=['POST'])
@login_required
def add_task_to_plan(plan_id):
    if current_user.role != 'parent':
        flash("Unauthorized access.", "error")
        return redirect(url_for('personal_dashboard'))

    plan = famjam_plans_collection.find_one({
        '_id': ObjectId(plan_id),
        'family_id': ObjectId(current_user.family_id)
    })
    if not plan:
        flash("Plan not found.", "error")
        return redirect(url_for('personal_dashboard'))

    try:
        name = request.form['name']
        points = int(request.form['points'])
        assigned_to = ObjectId(request.form['assigned_to'])
        due_date_str = request.form['due_date']
        due_date_aware = start_of_day_est(datetime.strptime(due_date_str, '%Y-%m-%d').date())

        # Check if due date is within the plan's range for organizational purposes
        plan_start = plan['start_date']
        plan_end = plan['end_date']
        if not (plan_start <= due_date_aware <= plan_end):
             flash(f"Warning: The due date is outside the active plan's range ({plan_start.strftime('%b %d')} - {plan_end.strftime('%b %d')}).", 'warning')


        events_collection.insert_one({
            'name': name,
            'description': request.form.get('description', ''),
            'points': points,
            'type': 'chore', # Manually added tasks are chores
            'family_id': ObjectId(current_user.family_id),
            'status': 'assigned',
            'created_at': now_est(),
            'assigned_to': assigned_to,
            'due_date': due_date_aware,
            'source_type': 'manual' # Identifier for manually added tasks
        })
        flash(f"Task '{name}' was added to the plan.", 'success')
    except Exception as e:
        flash(f"Error adding task: {e}", 'error')

    return redirect(url_for('manage_plan'))

################################################################################
# 9. CONTEXT PROCESSOR & OTHER ROUTES...
################################################################################

@app.context_processor
def inject_global_vars():
    if not current_user.is_authenticated:
        return {}
    family_members = list(users_collection.find({'family_id': current_user.family_id}))
    parent = {}
    family_doc = families_collection.find_one({'_id': ObjectId(current_user.family_id)})
    primary_parent_oid = family_doc['parent_ids'][0] if family_doc and family_doc.get('parent_ids') else None
    for member in family_members:
        member['_id'] = str(member['_id'])
        if primary_parent_oid and member['_id'] == str(primary_parent_oid):
            parent = member
    unread_messages_exist = direct_messages_collection.find_one({
        'recipient_id': ObjectId(current_user.id), 'is_read': False
    }) is not None
    return {
        'family_members': family_members, 'parent': parent,
        'unread_messages_exist': unread_messages_exist
    }

# All other routes from your file are included below...
@app.route('/child/reset-password/<child_id>', methods=['POST'])
@login_required
def reset_child_password(child_id):
    if current_user.role != 'parent':
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('personal_dashboard'))
    new_password = request.form.get('new_password')
    if not new_password or len(new_password) < 6:
        flash('Please provide a new password that is at least 6 characters long.', 'error')
        return redirect(url_for('personal_dashboard'))
    child = users_collection.find_one({'_id': ObjectId(child_id), 'family_id': current_user.family_id, 'role': 'child'})
    if not child:
        flash('Child not found in your family.', 'error')
        return redirect(url_for('personal_dashboard'))
    hashed_pw = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users_collection.update_one({'_id': ObjectId(child_id)}, {'$set': {'password_hash': hashed_pw}})
    flash(f"Password for {child.get('username')} has been reset.", 'success')
    return redirect(url_for('personal_dashboard'))

@app.route('/timer/create', methods=['POST'])
@login_required
def create_timer():
    timer_name = request.form.get('name', '').strip()
    timer_date_str = request.form.get('end_date', '')
    if not timer_name or not timer_date_str:
        flash("Timer name and date are required.", "error")
        return redirect(url_for('family_dashboard'))
    try:
        end_date = start_of_day_est(datetime.strptime(timer_date_str, '%Y-%m-%d').date())
    except ValueError:
        flash("Invalid date format.", "error")
        return redirect(url_for('family_dashboard'))
    timers_collection.insert_one({
        'name': timer_name, 'end_date': end_date,
        'family_id': ObjectId(current_user.family_id),
        'created_by': ObjectId(current_user.id),
        'created_at': now_est()
    })
    flash("Timer created!", "success")
    return redirect(url_for('family_dashboard'))

@app.route('/challenge/create', methods=['POST'])
@login_required
def create_challenge():
    title = request.form.get('title', '').strip()
    points_str = request.form.get('points', '0')
    if not title:
        flash("Challenge title is required.", "error")
        return redirect(url_for('family_dashboard'))
    try:
        points = int(points_str)
        if points <= 0: raise ValueError()
    except ValueError:
        flash("Invalid points value.", "error")
        return redirect(url_for('family_dashboard'))
    challenges_collection.insert_one({
        "family_id": ObjectId(current_user.family_id), "title": title, "points": points,
        "description": request.form.get('description', '').strip(), "status": "open",
        "created_by_id": ObjectId(current_user.id), "created_at": now_est()
    })
    flash("New family challenge posted!", "success")
    return redirect(url_for('family_dashboard'))

@app.route('/challenge/claim/<challenge_id>')
@login_required
def claim_challenge(challenge_id):
    if current_user.role != 'child':
        flash("Only children can claim challenges.", "error")
        return redirect(url_for('family_dashboard'))
    challenge = challenges_collection.find_one({'_id': ObjectId(challenge_id), 'family_id': ObjectId(current_user.family_id)})
    if not challenge or challenge['status'] != 'open':
        flash("This challenge cannot be claimed.", "error")
        return redirect(url_for('family_dashboard'))
    challenges_collection.update_one(
        {'_id': ObjectId(challenge_id)},
        {'$set': {'status': 'in_progress', 'claimed_by_id': ObjectId(current_user.id), 'claimed_at': now_est()}}
    )
    flash(f"You have claimed the challenge '{challenge['title']}'!", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/challenge/complete/<challenge_id>')
@login_required
def complete_challenge(challenge_id):
    challenge = challenges_collection.find_one({'_id': ObjectId(challenge_id), 'claimed_by_id': ObjectId(current_user.id), 'status': 'in_progress'})
    if not challenge:
        flash("This challenge could not be marked as complete.", "error")
        return redirect(url_for('personal_dashboard'))
    challenges_collection.update_one({'_id': ObjectId(challenge_id)}, {'$set': {'status': 'completed', 'completed_at': now_est()}})
    flash("Challenge marked complete! Awaiting approval.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/challenge/approve/<challenge_id>')
@login_required
def approve_challenge(challenge_id):
    if current_user.role != 'parent':
        flash("Only parents can approve challenges.", "error")
        return redirect(url_for('personal_dashboard'))
    challenge = challenges_collection.find_one({'_id': ObjectId(challenge_id), 'family_id': ObjectId(current_user.family_id), 'status': 'completed'})
    if not challenge:
        flash("This challenge is not ready for approval.", "error")
        return redirect(url_for('personal_dashboard'))
    users_collection.update_one(
        {'_id': challenge['claimed_by_id']},
        {'$inc': {'points': challenge['points'], 'lifetime_points': challenge['points']}}
    )
    challenges_collection.update_one({'_id': ObjectId(challenge_id)}, {'$set': {'status': 'approved', 'approved_at': now_est()}})
    flash(f"Challenge approved! {challenge['points']} points awarded.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/challenge/delete/<challenge_id>')
@login_required
def delete_challenge(challenge_id):
    challenge = challenges_collection.find_one({
        '_id': ObjectId(challenge_id), 'family_id': ObjectId(current_user.family_id),
        'created_by_id': ObjectId(current_user.id), 'status': 'open'
    })
    if not challenge:
        flash("You can only delete your own open challenges.", "error")
        return redirect(url_for('family_dashboard'))
    challenges_collection.delete_one({'_id': ObjectId(challenge_id)})
    flash("Challenge deleted.", "success")
    return redirect(url_for('family_dashboard'))

@app.route('/account/change-password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    if not current_password or not new_password or len(new_password) < 8:
        flash('All fields are required and new password must be 8+ characters.', 'error')
        return redirect(url_for('personal_dashboard'))
    user_data = users_collection.find_one({'_id': ObjectId(current_user.id)})
    if not user_data or not bcrypt.check_password_hash(user_data['password_hash'], current_password):
        flash('Your current password was incorrect.', 'error')
        return redirect(url_for('personal_dashboard'))
    hashed_pw = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users_collection.update_one({'_id': ObjectId(current_user.id)}, {'$set': {'password_hash': hashed_pw}})
    logout_user()
    flash('Password changed successfully. Please log in again.', 'success')
    return redirect(url_for('login'))

@app.route('/note/create', methods=['POST'])
@login_required
def create_note():
    content = request.form.get('note_content', '').strip()
    if content:
        notes_collection.insert_one({'user_id': ObjectId(current_user.id), 'content': content, 'created_at': now_est()})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/note/delete/<note_id>')
@login_required
def delete_note(note_id):
    notes_collection.delete_one({'_id': ObjectId(note_id), 'user_id': ObjectId(current_user.id)})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/todo/create', methods=['POST'])
@login_required
def create_todo():
    title = request.form.get('todo_title', '').strip()
    if title:
        personal_todos_collection.insert_one({'user_id': ObjectId(current_user.id), 'title': title, 'is_done': False, 'created_at': now_est()})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/todo/delete/<todo_id>')
@login_required
def delete_todo(todo_id):
    personal_todos_collection.delete_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/todo/toggle/<todo_id>')
@login_required
def toggle_todo(todo_id):
    todo = personal_todos_collection.find_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if todo:
        personal_todos_collection.update_one({'_id': ObjectId(todo_id)}, {'$set': {'is_done': not todo.get('is_done', False)}})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/message/send', methods=['POST'])
@login_required
def send_message():
    message_content = request.form.get('message_content', '').strip()
    recipient_id = request.form.get('recipient_id', '').strip()
    if not message_content or not recipient_id:
        return redirect(request.referrer or url_for('personal_dashboard'))
    recipient = users_collection.find_one({'_id': ObjectId(recipient_id), 'family_id': current_user.family_id})
    if not recipient:
        flash("Invalid recipient.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))
    direct_messages_collection.insert_one({
        "family_id": ObjectId(current_user.family_id), "sender_id": ObjectId(current_user.id),
        "sender_username": current_user.username, "recipient_id": ObjectId(recipient_id),
        "recipient_username": recipient.get('username', 'Unknown'), "message_content": message_content,
        "sent_at": now_est(), "is_read": False
    })
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"status": "success"})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/api/messages')
@login_required
def get_direct_messages():
    current_user_id = ObjectId(current_user.id)
    messages_cursor = direct_messages_collection.find({
        'family_id': ObjectId(current_user.family_id),
        '$or': [{'sender_id': current_user_id}, {'recipient_id': current_user_id}]
    }).sort('sent_at', DESCENDING)
    return jsonify(json.loads(json_util.dumps(messages_cursor)))

@app.route('/api/message/mark-read', methods=['POST'])
@login_required
def mark_messages_read():
    message_ids_str = request.get_json().get('message_ids', [])
    if not isinstance(message_ids_str, list):
        return jsonify({"error": "Invalid input format."}), 400
    message_ids_obj = [ObjectId(msg_id) for msg_id in message_ids_str]
    result = direct_messages_collection.update_many(
        {'_id': {'$in': message_ids_obj}, 'recipient_id': ObjectId(current_user.id)},
        {'$set': {'is_read': True}}
    )
    return jsonify({"status": "success", "modified_count": result.modified_count})

@app.route('/child/edit/<child_id>', methods=['POST'])
@login_required
def edit_child(child_id):
    if current_user.role != 'parent': return redirect(url_for('family_dashboard'))
    child = users_collection.find_one({'_id': ObjectId(child_id), 'family_id': current_user.family_id})
    if not child: return redirect(url_for('personal_dashboard'))
    update_data = {}
    new_username = request.form.get('username')
    new_password = request.form.get('password')
    if new_username and new_username != child.get('username'):
        if users_collection.find_one({'username': new_username, 'family_id': current_user.family_id, '_id': {'$ne': ObjectId(child_id)}}):
            flash('That username is already taken.', 'error')
            return redirect(url_for('personal_dashboard'))
        update_data['username'] = new_username
    if new_password:
        update_data['password_hash'] = bcrypt.generate_password_hash(new_password).decode('utf-8')
    if update_data:
        users_collection.update_one({'_id': ObjectId(child_id)}, {'$set': update_data})
        flash('Child information updated.', 'success')
    return redirect(url_for('personal_dashboard'))

@app.route('/child/remove/<child_id>')
@login_required
def remove_child(child_id):
    if current_user.role != 'parent': return redirect(url_for('family_dashboard'))
    child = users_collection.find_one({'_id': ObjectId(child_id), 'family_id': current_user.family_id, 'role': 'child'})
    if child:
        child_oid = ObjectId(child_id)
        users_collection.delete_one({'_id': child_oid})
        events_collection.delete_many({'assigned_to': child_oid})
        rewards_collection.delete_many({'requested_by_id': child_oid})
        transactions_collection.delete_many({'child_id': child_oid})
        moods_collection.delete_many({'user_id': child_oid})
        flash(f"{child.get('username')} has been removed from the family.", 'success')
    else:
        flash('Child not found.', 'error')
    return redirect(url_for('personal_dashboard'))

@app.route('/api/events')
@login_required
def api_events():
    fam_oid = ObjectId(current_user.family_id)
    child_colors = ['#ef4444', '#f97316', '#eab308', '#84cc16', '#22c55e', '#14b8a6', '#06b6d4', '#6366f1', '#a855f7', '#d946ef']
    fam_members = list(users_collection.find({'family_id': current_user.family_id}))
    member_map = {str(m['_id']): m['username'] for m in fam_members}
    child_color_map = {str(c['_id']): child_colors[i % len(child_colors)] for i, c in enumerate(m for m in fam_members if m.get('role') == 'child')}
    query = {'family_id': fam_oid}
    if (search := request.args.get('search')): query['name'] = regex.Regex(search, 'i')
    if (member_id := request.args.get('member')): query['assigned_to'] = ObjectId(member_id)
    if (etype := request.args.get('type')): query['type'] = etype

    cursor = events_collection.find(query)
    calendar_events = []
    for e in cursor:
        assigned_to_id_str = str(e.get('assigned_to'))
        can_checkin = False
        if e.get('type') == 'habit':
            last_completed_date_est = e.get('last_completed').astimezone(TIMEZONE).date() if e.get('last_completed') else None
            if not (last_completed_date_est and last_completed_date_est == today_est()):
                can_checkin = True
        calendar_events.append({
            'title': f"{e.get('type', 'Task').capitalize()}: {e['name']}", 'start': e['due_date'].isoformat(),
            'allDay': True, 'color': child_color_map.get(assigned_to_id_str, '#6b7280'),
            'extendedProps': {
                '_id': str(e['_id']), 'type': e.get('type'), 'description': e.get('description', ''),
                'points': e.get('points'), 'status': e.get('status'), 'assignee_name': member_map.get(assigned_to_id_str, 'N/A'),
                'assigned_to': assigned_to_id_str, 'can_checkin': can_checkin
            }
        })
    return jsonify(calendar_events)

@app.route('/api/mood/log', methods=['POST'])
@login_required
def api_mood_log():
    data = request.json
    try:
        entry_date_aware = start_of_day_est(datetime.strptime(data['date'], '%Y-%m-%d').date())
        mood_score = MOOD_EMOJI_TO_SCORE.get(data['emoji'])
        if not all([data['period'], data['emoji'], mood_score is not None]):
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400
        moods_collection.update_one(
            {'user_id': ObjectId(current_user.id), 'date': entry_date_aware, 'period': data['period']},
            {'$set': {'mood_emoji': data['emoji'], 'mood_score': mood_score, 'note': data.get('note', ''), 'updated_at': now_est()},
             '$setOnInsert': {'family_id': ObjectId(current_user.family_id), 'created_at': now_est()}},
            upsert=True
        )
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/mood/personal')
@login_required
def api_mood_personal():
    if 'date' in request.args and 'period' in request.args:
        try:
            entry_date_aware = start_of_day_est(datetime.strptime(request.args['date'], '%Y-%m-%d').date())
            entry = moods_collection.find_one({'user_id': ObjectId(current_user.id), 'date': entry_date_aware, 'period': request.args['period']})
            return jsonify(entry) if entry else jsonify({'error': 'Not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    thirty_days_ago = now_est() - timedelta(days=30)
    mood_entries = list(moods_collection.find({'user_id': ObjectId(current_user.id), 'date': {'$gte': thirty_days_ago}}).sort('date', ASCENDING))
    labels = [f"{e['date'].astimezone(TIMEZONE).strftime('%b %d')} {e['period']}" for e in mood_entries]
    data = [e['mood_score'] for e in mood_entries]
    return jsonify({'labels': labels, 'data': data})

@app.route('/api/mood/family')
@login_required
def api_mood_family():
    thirty_days_ago = now_est() - timedelta(days=30)
    match_query = {'family_id': ObjectId(current_user.family_id), 'date': {'$gte': thirty_days_ago}}
    daily_avg_data = list(moods_collection.aggregate([
        {'$match': match_query}, {'$group': {'_id': '$date', 'avgScore': {'$avg': '$mood_score'}}}, {'$sort': {'_id': 1}}
    ]))
    dist_data = list(moods_collection.aggregate([
        {'$match': match_query}, {'$group': {'_id': '$mood_emoji', 'count': {'$sum': 1}}}, {'$sort': {'count': -1}}
    ]))
    mood_map = {m['emoji']: m for m in MOOD_CONFIG['moods']}
    return jsonify({
        'daily_average': {
            'labels': [d['_id'].astimezone(TIMEZONE).strftime('%b %d') for d in daily_avg_data],
            'data': [round(d['avgScore'], 2) for d in daily_avg_data]
        },
        'distribution': {
            'labels': [f"{d['_id']} ({mood_map.get(d['_id'], {}).get('desc', '')})" for d in dist_data],
            'data': [d['count'] for d in dist_data],
            'colors': [mood_map.get(d['_id'], {}).get('color', '#cccccc') for d in dist_data]
        }
    })

@app.route('/manage-plan')
@login_required
def manage_plan():
    if current_user.role != 'parent':
        flash("You don't have permission to view this page.", "error")
        return redirect(url_for('personal_dashboard'))
    
    family_oid = ObjectId(current_user.family_id)
    active_plan = famjam_plans_collection.find_one({'family_id': family_oid, 'status': 'active'})

    if not active_plan:
        flash("No active FamJam plan to manage.", "error")
        return redirect(url_for('personal_dashboard'))

    sort_by = request.args.get('sort_by', 'due_date')
    order = ASCENDING if request.args.get('order', 'asc') == 'asc' else DESCENDING

    start_date_aware = start_of_day_est(active_plan['start_date'].date())
    end_date_aware = start_of_day_est(active_plan['end_date'].date())

    tasks_cursor = events_collection.find({
        'family_id': family_oid, 
        'due_date': {'$gte': start_date_aware, '$lte': end_date_aware}
    }).sort(sort_by, order)

    family_members = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}))
    
    # ✨ FIX 1: Convert each member's ObjectId to a string before passing to the template.
    for member in family_members:
        member['_id'] = str(member['_id'])

    member_map = {m['_id']: m['username'] for m in family_members}

    tasks = []
    for task in tasks_cursor:
        task['assigned_to_username'] = member_map.get(str(task.get('assigned_to')), 'N/A')
        # ✨ FIX 2: Use default=str to handle non-serializable types like ObjectId and datetime.
        task['json_string'] = json.dumps(task, default=str)
        tasks.append(task)

    return render_template(
        'index.html', 
        page='manage_plan', 
        plan=active_plan, 
        tasks=tasks,
        family_members=family_members, 
        current_sort={'by': sort_by, 'order': request.args.get('order', 'asc')},
        TIMEZONE=TIMEZONE
    )
@app.route('/plan/edit_name/<plan_id>', methods=['POST'])
@login_required
def edit_plan_name(plan_id):
    if current_user.role != 'parent': return redirect(url_for('personal_dashboard'))
    new_name = request.form.get('plan_name', '').strip()
    if not new_name:
        flash("Plan name cannot be empty.", "error")
        return redirect(url_for('manage_plan'))
    famjam_plans_collection.update_one(
        {'_id': ObjectId(plan_id), 'family_id': ObjectId(current_user.family_id)},
        {'$set': {'plan_data.plan_name': new_name}}
    )
    flash("Plan name updated.", "success")
    return redirect(url_for('manage_plan'))


@app.route('/api/reward/suggest', methods=['POST'])
@login_required
def suggest_rewards():
    """AI-powered endpoint for parents to get reward suggestions."""
    if current_user.role != 'parent' or not openai_client:
        return jsonify({"error": "Not authorized or AI not configured."}), 403

    theme = request.get_json().get('theme', 'general motivation and fun activities')
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'username': 1, '_id': 0}))
    child_names = [c['username'] for c in children]
    child_info = f"for children named {', '.join(child_names)}" if child_names else "for children"
    
    system_prompt = f"""
    You are an expert in child development and positive reinforcement.
    Generate a JSON object containing a key "suggested_rewards".
    This key should hold an array of 5-7 creative and engaging reward ideas {child_info}.
    The theme for the rewards is: "{theme}".
    Each reward object in the array must have two keys:
    1. "name": A short, descriptive string for the reward (e.g., "Extra 30 Minutes of Screen Time").
    2. "cost": An integer representing the point cost, ranging from 50 to 1000, scaled appropriately to the reward's value.
    Ensure the output is a valid JSON object.
    """
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the reward suggestions."}
            ]
        )
        suggestions = json.loads(response.choices[0].message.content)
        return jsonify(suggestions)
    except Exception as e:
        return jsonify({"error": f"Failed to generate reward suggestions: {str(e)}"}), 500


@app.route('/api/famjam/suggest', methods=['POST'])
@login_required
def suggest_famjam_plan():
    if current_user.role != 'parent' or not openai_client:
        return jsonify({"error": "Not authorized or AI not configured."}), 403
    goal = request.get_json().get('goal', 'general family teamwork')
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'username': 1, '_id': 0}))
    if not children:
        return jsonify({"error": "You need at least one child to create a plan."}), 400
    child_names = [c['username'] for c in children]
    system_prompt = f"""Generate a JSON object for a chore plan for children: {', '.join(child_names)}. The goal is: "{goal}". The JSON must have "plan_name" (string) and "suggested_chores" (array of objects with "name", "description", "points" (10-50), "type": "chore", and "recurrence" ('daily', 'weekly', 'monthly')). Generate 5-7 chores."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini", response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": "Generate the plan."}]
        )
        plan_json = json.loads(response.choices[0].message.content)
    except Exception as e:
        return jsonify({"error": f"Failed to generate plan: {str(e)}"}), 500
    today = now_est()
    quarter = (today.month - 1) // 3 + 1
    start_month = (quarter - 1) * 3 + 1
    start_date_aware = start_of_day_est(today.replace(month=start_month, day=1).date())
    end_date_aware = start_of_day_est((start_date_aware + relativedelta(months=3) - timedelta(days=1)).date())
    plan_id = famjam_plans_collection.insert_one({
        'plan_data': plan_json, 'goal': goal, 'family_id': ObjectId(current_user.family_id),
        'status': 'draft', 'start_date': start_date_aware, 'end_date': end_date_aware, 'created_at': now_est()
    }).inserted_id
    plan_json.update({
        'plan_id': str(plan_id), 'start_date_str': start_date_aware.strftime('%B %d, %Y'),
        'end_date_str': end_date_aware.strftime('%B %d, %Y')
    })
    return jsonify(plan_json)

@app.route('/api/famjam/apply', methods=['POST'])
@login_required
def apply_famjam_plan():
    if current_user.role != 'parent': return jsonify({"error": "Unauthorized"}), 403
    plan_data = request.json
    plan_id_str = plan_data.get('plan_id')
    if not plan_data or 'suggested_chores' not in plan_data or not plan_id_str:
        return jsonify({'error': 'Invalid plan format.'}), 400
    family_oid = ObjectId(current_user.family_id)
    famjam_plans_collection.update_many({'family_id': family_oid, 'status': 'active'}, {'$set': {'status': 'archived'}})
    famjam_plans_collection.update_one(
        {'_id': ObjectId(plan_id_str)},
        {'$set': {'status': 'active', 'applied_at': now_est(), 'plan_data': {'plan_name': plan_data.get('plan_name'), 'suggested_chores': plan_data.get('suggested_chores', [])}}}
    )
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'_id': 1}))
    if not children: return jsonify({"error": "No children found."}), 400
    child_ids = [str(c['_id']) for c in children]
    child_cycler = itertools.cycle(child_ids)
    current_due_date = start_of_day_est(today_est())
    end_date = current_due_date + timedelta(days=90)
    new_events = []
    for chore_template in plan_data.get('suggested_chores', []):
        delta = {'daily': timedelta(days=1), 'weekly': timedelta(weeks=1), 'monthly': relativedelta(months=1)}.get(chore_template.get('recurrence'))
        if not delta: continue
        assigned_to_value = chore_template.get('assigned_to')
        loop_date = current_due_date
        while loop_date < end_date:
            assignees = child_ids if assigned_to_value == "__ALL__" else [assigned_to_value] if assigned_to_value in child_ids else [next(child_cycler)]
            for cid in assignees:
                new_events.append({
                    'name': chore_template.get('name'), 'description': chore_template.get('description'), 'points': int(chore_template.get('points', 0)),
                    'type': 'chore', 'family_id': family_oid, 'status': 'assigned', 'created_at': now_est(),
                    'assigned_to': ObjectId(cid), 'due_date': loop_date
                })
            loop_date += delta
    if not new_events: return jsonify({'status': 'warning', 'message': 'No new chores scheduled.'})
    try:
        events_collection.insert_many(new_events, ordered=False)
        return jsonify({'status': 'success', 'message': f'{len(new_events)} chores scheduled!'})
    except Exception as e:
        if "E11000 duplicate key error" in str(e):
            return jsonify({'status': 'success', 'message': 'Plan applied. Existing chores were not duplicated.'})
        return jsonify({'error': f'Failed to save: {e}'}), 500

@app.route('/api/consult-ai', methods=['POST'])
@login_required
def consult_ai():
    if not openai_client: return jsonify({"error": "AI not configured."}), 503
    mood_entries = list(moods_collection.find({'user_id': ObjectId(current_user.id), 'date': {'$gte': now_est() - timedelta(days=30)}}).sort('date', ASCENDING))
    if len(mood_entries) < 5:
        return jsonify({"ai_response": "### Not Enough Data\n\nPlease log at least 5 moods for a meaningful analysis."}), 200
    mood_log_str = ""
    for entry in mood_entries:
        mood_desc = next((m['desc'] for m in MOOD_CONFIG['moods'] if m['score'] == entry['mood_score']), '')
        date_est = entry['date'].astimezone(TIMEZONE).strftime('%Y-%m-%d')
        mood_log_str += f"- On {date_est} ({entry['period']}), I felt: {mood_desc}. Note: '{entry.get('note', 'N/A')}'\n"
    system_prompt = """You are 'FAMJAM Insights', a supportive AI assistant. Start with a disclaimer that you are not a medical professional. Analyze the user's mood log in Markdown, providing a summary, potential patterns, 2-3 actionable suggestions, and an encouraging closing. Be positive and empathetic."""
    user_prompt = f"Here is my mood log. Please analyze it:\n\n{mood_log_str}"
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        )
        return jsonify({"ai_response": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": f"AI service error: {str(e)}"}), 500

@app.route('/parent/create_child', methods=['POST'])
@login_required
def create_child_direct():
    if current_user.role != 'parent':
        flash("Only parents can create child accounts.", 'error')
        return redirect(url_for('personal_dashboard'))
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not username or len(password) < 6:
        flash('Username and a password of at least 6 characters are required.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))
    if users_collection.find_one({'username': username, 'family_id': current_user.family_id}):
        flash(f"The username '{username}' is already taken in your family.", 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))
    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    users_collection.insert_one({
        'username': username, 'password_hash': hashed_pw, 'role': 'child',
        'family_id': current_user.family_id, 'points': 0, 'lifetime_points': 0
    })
    flash(f"Child account for '{username}' created!", 'success')
    return redirect(url_for('personal_dashboard'))

@app.route('/parent/create_another_parent', methods=['POST'])
@login_required
def create_another_parent():
    if current_user.role != 'parent': return redirect(url_for('family_dashboard'))
    family = families_collection.find_one({'_id': ObjectId(current_user.family_id)})
    if not family or not family.get('parent_ids') or family['parent_ids'][0] != ObjectId(current_user.id):
        flash("Only the primary parent may add another parent.", 'error')
        return redirect(url_for('family_dashboard'))
    email = request.form.get('email', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not email or not username or not password:
        flash('All fields are required.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))
    if users_collection.find_one({'$or': [{'email': email}, {'username': username, 'family_id': current_user.family_id}]}):
        flash('That email or username is already in use.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))
    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    new_parent_id = users_collection.insert_one({
        'email': email, 'username': username, 'password_hash': hashed_pw, 'role': 'parent',
        'family_id': current_user.family_id, 'points': 0, 'lifetime_points': 0
    }).inserted_id
    families_collection.update_one({'_id': ObjectId(current_user.family_id)}, {'$push': {'parent_ids': new_parent_id}})
    flash(f"Parent account for '{username}' created!", 'success')
    return redirect(url_for('personal_dashboard'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)