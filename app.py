import os
import io
import json
# import csv # Not used, commented out
import itertools
import qrcode
from datetime import datetime, timedelta, date, timezone
from collections import defaultdict
import pytz # Import timezone library
import math # For penalty calculation

# Added for scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

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
import openai # If using the official OpenAI library

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

# --- Penalty Configuration ---
MISSED_TASK_PENALTY_FACTOR = 0.5

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
rewards_collection = db['rewards']
transactions_collection = db['transactions']
moods_collection = db['moods']
famjam_plans_collection = db['famjam_plans']
timers_collection = db['timers']
notes_collection = db['notes']
personal_todos_collection = db['personal_todos']
challenges_collection = db['challenges']
direct_messages_collection = db['direct_messages']
families_collection = db['families']
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
events_collection.create_index([('due_date', ASCENDING), ('status', ASCENDING)])
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
        self.cash_balance = user_data.get('cash_balance', 0.0) # ADDED

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
        # Handle pytz timezone objects specifically if needed elsewhere, though unlikely for API responses
        # if isinstance(obj, pytz.tzinfo.BaseTzInfo):
        #     return str(obj) # Return the string representation
        return json_util.default(obj)

app.json_encoder = MongoJsonEncoder

################################################################################
# 5. BACKGROUND TASK FUNCTION
################################################################################
def mark_missed_tasks():
    with app.app_context():
        print(f"[{datetime.now()}] Running mark_missed_tasks job...")
        try:
            yesterday_date = today_est() - timedelta(days=1)
            start_of_yesterday_est = start_of_day_est(yesterday_date)
            start_of_today_est = start_of_day_est(today_est())
            start_utc = start_of_yesterday_est.astimezone(pytz.utc)
            end_utc = start_of_today_est.astimezone(pytz.utc)
            missed_tasks_cursor = events_collection.find({
                'due_date': {'$gte': start_utc, '$lt': end_utc},
                'status': 'assigned'
            })
            event_updates = []
            user_penalties = defaultdict(int)
            now = now_est()
            for task in missed_tasks_cursor:
                penalty = math.floor(task.get('points', 0) * MISSED_TASK_PENALTY_FACTOR)
                event_updates.append(UpdateOne(
                    {'_id': task['_id']},
                    {'$set': {'status': 'missed', 'missed_at': now}}
                ))
                if penalty > 0 and task.get('assigned_to'):
                    user_penalties[task['assigned_to']] += penalty
            if event_updates:
                events_collection.bulk_write(event_updates)
                print(f"Marked {len(event_updates)} tasks as missed.")
            if user_penalties:
                # --- MODIFICATION ---
                # This pipeline update ensures points can never drop below 0
                user_updates = [UpdateOne({'_id': uid}, [{'$set': {'points': {'$max': [0, {'$subtract': ['$points', penalty]}]}}}]) for uid, penalty in user_penalties.items()]
                # --- END MODIFICATION ---
                users_collection.bulk_write(user_updates)
                print(f"Applied penalties to {len(user_updates)} users (floored at 0).")
            if not event_updates and not user_penalties:
                print("No tasks found to mark as missed.")
        except Exception as e:
            print(f"Error in mark_missed_tasks job: {e}")
        finally:
            print(f"[{datetime.now()}] Finished mark_missed_tasks job.")

################################################################################
# 6. SCHEDULER SETUP
################################################################################
scheduler = BackgroundScheduler(daemon=True, timezone=TIMEZONE_NAME)
scheduler.add_job(mark_missed_tasks, trigger=CronTrigger(hour=2, minute=5))
if not scheduler.running:
    try:
        scheduler.start()
        print("Scheduler started successfully.")
    except Exception as e:
        print(f"Error starting scheduler: {e}")

################################################################################
# 7. BASIC / AUTH ROUTES
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
    # Assuming you have a login.html template
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

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
    parent = users_collection.find_one({'_id': first_parent_id}) if first_parent_id else None
    parent_name = parent.get('username', 'your family organizer') if parent else 'your family organizer'
    # Assuming you have a join_family.html template
    return render_template('join_family.html', parent_name=parent_name, invite_code=invite_code)

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
        new_id = users_collection.insert_one({
            'email': email, 'username': username, 'password_hash': hashed_pw,
            'role': 'parent', 'family_id': str(family_id),
            'lifetime_points': 0, 'points': 0, 'cash_balance': 0.0
        }).inserted_id
        families_collection.update_one({'_id': family_id}, {'$push': {'parent_ids': new_id}})
        flash('Parent account created! Please log in.', 'success')
        return redirect(url_for('login'))
    # Assuming you have a register_parent.html template
    return render_template('register_parent.html')

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
            'lifetime_points': 0, 'points': 0, 'cash_balance': 0.0
        }).inserted_id
        families_collection.update_one({'_id': ObjectId(family_id)}, {'$push': {'parent_ids': new_parent_id}})
        flash(f'Welcome to {family.get("name", "the family")}! Please log in.', 'success')
        return redirect(url_for('login'))
    family_name = family.get('name', 'Family')
    # Reuse the register_parent template
    return render_template('register_parent.html', family_id=family_id, family_name=family_name)

@app.route('/join')
@login_required
def invite():
    if current_user.role != 'parent':
        return redirect(url_for('personal_dashboard'))
    invite_url = f"{BASE_URL}{url_for('join_family', invite_code=current_user.family_id)}"
    # Assuming you have an invite.html template
    return render_template('invite.html', invite_url=invite_url)

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
        if not families_collection.find_one({'_id': ObjectId(invite_code)}):
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
            'family_id': invite_code, 'points': 0, 'lifetime_points': 0, 'cash_balance': 0.0
        })
        flash('Child account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    # Assuming you have a register_child.html template
    return render_template('register_child.html', invite_code=invite_code)

################################################################################
# 8. DASHBOARD & CORE VIEW ROUTES
################################################################################

@app.route('/dashboard')
@login_required
def personal_dashboard():
    family_oid = ObjectId(current_user.family_id)
    today = today_est() # Get today's date in EST

    if current_user.role == 'parent':
        family_members = list(users_collection.find(
            {'family_id': current_user.family_id},
            # Projection to fetch only necessary fields
            {'_id': 1, 'username': 1, 'role': 1, 'points': 1, 'cash_balance': 1}
        ))
        member_map = {str(m['_id']): m['username'] for m in family_members}

        child_dashboard_data = []
        children = [m for m in family_members if m.get('role') == 'child']

        # Get timezone-aware start/end times for today and the week
        now = now_est()
        start_of_today = start_of_day_est(today) # Timezone-aware midnight EST
        end_of_today = start_of_today + timedelta(days=1)
        start_of_week = start_of_day_est(today - timedelta(days=now.weekday()))
        end_of_week = start_of_week + timedelta(days=7)

        for child in children:
            child_id_obj = child['_id'] # Use the ObjectId directly from the loop

            # --- Task Calculations (Existing) ---
            todays_tasks = list(events_collection.find({
                'assigned_to': child_id_obj,
                'due_date': {'$gte': start_of_today, '$lt': end_of_today}
            }))
            todays_total = len(todays_tasks)
            todays_completed = sum(1 for t in todays_tasks if t.get('status') in ['completed', 'approved'])
            todays_missed = sum(1 for t in todays_tasks if t.get('status') == 'missed')
            overdue_count = events_collection.count_documents({
                'assigned_to': child_id_obj,
                'type': 'chore',
                'status': 'assigned',
                'due_date': {'$lt': start_of_today} # Compare against aware datetime
            })

            weekly_tasks = list(events_collection.find({
                'assigned_to': child_id_obj,
                'due_date': {'$gte': start_of_week, '$lt': end_of_week}
            }))
            missed_this_week_tasks = [t for t in weekly_tasks if t.get('status') == 'missed']
            weekly_missed_count = len(missed_this_week_tasks)
            weekly_penalty_incurred = sum(math.floor(t.get('points', 0) * MISSED_TASK_PENALTY_FACTOR) for t in missed_this_week_tasks)
            weekly_potential_points = sum(t.get('points', 0) for t in weekly_tasks if t.get('status') not in ['missed', 'forgiven'])

            # --- Fetch Today's Moods for this Child ---
            todays_moods = list(moods_collection.find({
                'user_id': child_id_obj,
                'date': start_of_today # Query using the timezone-aware start of today
            }))
            # Extract just the period names ('Morning', 'Afternoon', 'Evening')
            logged_periods = [m.get('period') for m in todays_moods if m.get('period')]
            # --- END Mood Fetch ---

            # Append all data for this child
            child_dashboard_data.append({
                '_id': str(child_id_obj),
                'username': child.get('username'),
                'points': child.get('points', 0),
                'cash_balance': child.get('cash_balance', 0.0),
                'today': {
                    'total': todays_total,
                    'completed': todays_completed,
                    'missed': todays_missed,
                    'overdue': overdue_count,
                    'progress': int((todays_completed / todays_total * 100)) if todays_total > 0 else 100
                },
                'week': {
                    'total_tasks': len(weekly_tasks),
                    'potential_points': weekly_potential_points,
                    'missed_count': weekly_missed_count,
                    'penalty_incurred': weekly_penalty_incurred
                },
                'today_moods_logged': logged_periods
            })

        # Convert ObjectIds to strings for remaining processing
        for member in family_members: member['_id'] = str(member['_id'])

        # --- Fetch Pending Events & Rewards (Existing) ---
        pending_events = list(events_collection.find({'family_id': family_oid, 'status': 'completed'}).sort('completed_at', DESCENDING))
        available_rewards = list(store_rewards_collection.find({'family_id': family_oid}).sort('cost', ASCENDING))
        pending_rewards = list(rewards_collection.find({'family_id': family_oid, 'status': 'pending'}).sort('requested_at', DESCENDING))

        # Populate usernames for pending rewards
        user_ids_for_rewards = [r['requested_by_id'] for r in pending_rewards]
        users_for_rewards = {str(u['_id']): u['username'] for u in users_collection.find({'_id': {'$in': user_ids_for_rewards}})}
        for reward_req in pending_rewards:
             reward_req['username'] = users_for_rewards.get(str(reward_req.get('requested_by_id')), 'Unknown')

        # Render the parent dashboard template
        # *** FIX: Added MOOD_CONFIG here ***
        return render_template(
            'dashboard_parent.html',
            family_members=family_members, # Used in loops/dropdowns
            member_map=member_map,         # Used for mapping IDs to names
            child_dashboard_data=child_dashboard_data, # Contains all child stats including moods
            pending_events=pending_events,
            pending_rewards=pending_rewards,
            available_rewards=available_rewards,
            TIMEZONE=TIMEZONE_NAME,        # Pass timezone name string
            TIMEZONE_OBJ=TIMEZONE,         # Pass pytz object for filters if needed
            MOOD_CONFIG=MOOD_CONFIG        # *** ADDED THIS LINE ***
        )

    else: # Child Dashboard
        # ... (child dashboard logic remains unchanged) ...
        current_user_oid = ObjectId(current_user.id)
        now = now_est()
        start_of_today = start_of_day_est(today)
        start_of_week = start_of_day_est(today - timedelta(days=now.weekday()))
        end_of_week = start_of_week + timedelta(days=7)
        parent = {}
        family_doc = families_collection.find_one({'_id': family_oid})
        if family_doc and family_doc.get('parent_ids'):
            parent_doc = users_collection.find_one({'_id': family_doc['parent_ids'][0]})
            if parent_doc: parent = {'_id': str(parent_doc['_id']), 'username': parent_doc.get('username')}

        weekly_tasks_cursor = events_collection.find({'assigned_to': current_user_oid, 'due_date': {'$gte': start_of_week, '$lt': end_of_week}})
        missed_this_week_tasks = [t for t in list(weekly_tasks_cursor) if t.get('status') == 'missed']

        child_stats = {'weekly_missed_count': len(missed_this_week_tasks), 'weekly_penalty_incurred': sum(math.floor(t.get('points', 0) * MISSED_TASK_PENALTY_FACTOR) for t in missed_this_week_tasks)}
        overdue_events = list(events_collection.find({'assigned_to': current_user_oid, 'type': 'chore', 'status': 'assigned', 'due_date': {'$lt': start_of_today}}).sort('due_date', ASCENDING))
        todays_events_cursor = events_collection.find({'assigned_to': current_user_oid, 'due_date': {'$gte': start_of_today, '$lt': start_of_today + timedelta(days=1)}}).sort([('status', ASCENDING), ('type', DESCENDING)])
        todays_events = []
        for event in todays_events_cursor:
            event['can_checkin'] = False
            if event.get('type') == 'habit' and event.get('status') not in ['missed', 'forgiven']:
                last_completed = event.get('last_completed')
                last_completed_date = last_completed.astimezone(TIMEZONE).date() if last_completed else None
                if not last_completed_date or last_completed_date != today:
                    event['can_checkin'] = True
            todays_events.append(event)
        available_rewards = list(store_rewards_collection.find({'family_id': family_oid}).sort('cost', ASCENDING))
        rewards = list(rewards_collection.find({'requested_by_id': current_user_oid}))
        for r in rewards:
            if r.get('resolved_at'):
                delta = now - r['resolved_at'].astimezone(TIMEZONE)
                if delta.days > 0: r['resolved_at_pretty'] = f"{delta.days}d ago"
                elif (h := delta.seconds // 3600) > 0: r['resolved_at_pretty'] = f"{h}h ago"
                else: r['resolved_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"
        family_members = list(users_collection.find({'family_id': str(family_oid)}))
        member_map = {str(m['_id']): m['username'] for m in family_members}
        challenges = list(challenges_collection.find({'family_id': family_oid, 'status': {'$in': ['open', 'in_progress', 'completed']}}).sort('created_at', DESCENDING))
        for c in challenges: c['claimer_username'] = member_map.get(str(c.get('claimed_by_id')), '')

        # *** FIX: Added MOOD_CONFIG here ***
        return render_template(
            'dashboard_child.html',
            todays_events=todays_events,
            overdue_events=overdue_events,
            child_stats=child_stats,
            rewards=rewards,
            available_rewards=available_rewards,
            challenges=challenges,
            parent=parent,
            TIMEZONE=TIMEZONE_NAME,
            TIMEZONE_OBJ=TIMEZONE,
            MOOD_CONFIG=MOOD_CONFIG        # *** ADDED THIS LINE ***
        )

@app.route('/family-dashboard')
@login_required
def family_dashboard():
    fam_oid = ObjectId(current_user.family_id)
    family_members = list(users_collection.find({'family_id': current_user.family_id}))
    member_map = {str(m['_id']): m['username'] for m in family_members}
    for member in family_members: member['_id'] = str(member['_id'])
    stats = { "completed_this_week": 0, "pending_approval": 0, "total_points_awarded": sum(m.get('lifetime_points', 0) for m in family_members if m.get('role') == 'child'), "weekly_completion_data": {"labels": [], "data": []} }
    now = now_est()
    one_week_ago = now - timedelta(days=7)
    day_counts = {(now.date() - timedelta(days=i)).strftime('%a'): 0 for i in range(7)}
    for e in events_collection.find({'family_id': fam_oid}):
        if e.get('status') == 'completed': stats['pending_approval'] += 1
        if e.get('status') == 'approved' and e.get('approved_at') and e['approved_at'].astimezone(TIMEZONE) > one_week_ago:
            stats['completed_this_week'] += 1
            day_label = e['approved_at'].astimezone(TIMEZONE).strftime('%a')
            if day_label in day_counts: day_counts[day_label] += 1
    stats['weekly_completion_data']['labels'] = list(day_counts.keys())[::-1]
    stats['weekly_completion_data']['data'] = list(day_counts.values())[::-1]
    rec_cursor = events_collection.find({'family_id': fam_oid, 'status': 'approved'}).sort('approved_at', DESCENDING).limit(5)
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
        # Assuming end_date in DB is already timezone-aware (e.g., stored as UTC or localized EST)
        # If it's naive, it needs localization first. start_of_day_est handles this if passed a date object.
        end_date_aware = t['end_date'].astimezone(TIMEZONE) # Ensure it's in EST for display and calc
        delta = end_date_aware - now
        time_left = "Timer ended"
        if delta.total_seconds() >= 0:
            days_left = delta.days
            if days_left >= 1:
                time_left = f"{days_left} day{'s' if days_left != 1 else ''} left"
            else:
                # Calculate hours/minutes remaining within the current day
                seconds_remaining_today = (end_date_aware.replace(hour=23, minute=59, second=59) - now).total_seconds()
                if seconds_remaining_today < 0: seconds_remaining_today = 0 # Avoid negative if now is past end_date today

                hours, rem = divmod(seconds_remaining_today, 3600)
                minutes, _ = divmod(rem, 60)
                hours = int(hours)
                minutes = int(minutes)
                if hours > 0: time_left = f"{hours} hour{'s' if hours != 1 else ''} left"
                elif minutes > 0: time_left = f"{minutes} minute{'s' if minutes != 1 else ''} left"
                else: time_left = "Less than a minute left"

        timers.append({'_id': str(t['_id']), 'name': t['name'], 'end_date': end_date_aware.strftime('%b %d, %Y'), 'creator_id': str(t.get('created_by')), 'creator_name': member_map.get(str(t.get('created_by')), "Unknown"), 'time_left': time_left})

    # Assuming family_dashboard.html template exists
    return render_template('family_dashboard.html', stats=stats, family_members=family_members, recent_events=recent_events, timers=timers, now=now_est())


@app.route('/calendar-focus')
@login_required
def calendar_focus():
    family_members = list(users_collection.find({'family_id': current_user.family_id}))
    for member in family_members: member['_id'] = str(member['_id'])
    # Assuming calendar_focus.html template exists
    return render_template('calendar_focus.html', family_members=family_members)

@app.route('/mood-dashboard/personal')
@login_required
def mood_dashboard_personal():
    # Assuming mood_dashboard_personal.html template exists
    return render_template('mood_dashboard_personal.html', mood_config=MOOD_CONFIG)

@app.route('/mood-dashboard/family')
@login_required
def mood_dashboard_family():
    if current_user.role != 'parent':
        flash("Only parents can view the family mood dashboard.", "error")
        return redirect(url_for('mood_dashboard_personal'))
    # Assuming mood_dashboard_family.html template exists
    return render_template('mood_dashboard_family.html', mood_config=MOOD_CONFIG)

@app.route('/service-worker.js')
def service_worker():
    return app.send_static_file('service-worker.js')

################################################################################
# 9. CASH, REWARD, & ACCOUNT MGMT ROUTES
################################################################################

@app.route('/update_cash_balance/<string:child_id>', methods=['POST'])
@login_required
def update_cash_balance(child_id):
    if current_user.role != 'parent':
        flash('Unauthorized access.', 'error')
        return redirect(url_for('personal_dashboard'))
    try:
        child_oid = ObjectId(child_id)
        child = users_collection.find_one({'_id': child_oid, 'family_id': current_user.family_id, 'role': 'child'})
        if not child:
             flash('Child not found or not in your family.', 'error')
             return redirect(url_for('personal_dashboard'))
        new_balance_str = request.form.get('new_balance')
        if new_balance_str is None: raise ValueError("New balance not provided.")
        new_balance = float(new_balance_str)
        if new_balance < 0: raise ValueError("Balance cannot be negative.")
        users_collection.update_one({'_id': child_oid}, {'$set': {'cash_balance': new_balance}})
        flash(f"{child.get('username')}'s balance updated to ${new_balance:.2f}.", 'success')
    except ValueError as e:
        flash(f'Invalid input: {e}', 'error')
    except Exception as e:
        flash(f'An error occurred: {e}', 'error')
        print(f"Error updating balance for child {child_id}: {e}")
    return redirect(url_for('personal_dashboard'))

@app.route('/reward/request/resolve/<request_id>', methods=['POST'])
@login_required
def resolve_reward_request(request_id):
    if current_user.role != 'parent': return redirect(url_for('personal_dashboard'))
    action = request.form.get('action')
    try:
        req_oid = ObjectId(request_id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid request ID.", "error")
        return redirect(url_for('personal_dashboard'))
    reward_request = rewards_collection.find_one({'_id': req_oid, 'family_id': fam_oid})
    if not reward_request or reward_request['status'] != 'pending':
        flash("Reward request not found or already resolved.", "error")
        return redirect(url_for('personal_dashboard'))
    update_doc = {'$set': {'status': action, 'resolved_at': now_est(), 'resolved_by_id': ObjectId(current_user.id)}}
    if action == 'approve':
        rewards_collection.update_one({'_id': req_oid}, update_doc)
        flash(f"Request for '{reward_request['reward_name']}' approved.", "success")
    elif action == 'deny':
        users_collection.update_one({'_id': reward_request['requested_by_id']}, {'$inc': {'points': reward_request['cost']}})
        rewards_collection.update_one({'_id': req_oid}, update_doc)
        flash(f"Request for '{reward_request['reward_name']}' denied. Points refunded.", "info")
    return redirect(url_for('personal_dashboard'))

@app.route('/reward/request', methods=['POST'])
@login_required
def request_reward():
    if current_user.role != 'child':
        flash("Only children can request rewards.", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        reward_id = ObjectId(request.form.get('reward_id'))
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid reward ID.", "error")
        return redirect(url_for('personal_dashboard'))
    reward = store_rewards_collection.find_one({'_id': reward_id, 'family_id': fam_oid})
    if not reward:
        flash("This reward is not available.", "error")
        return redirect(url_for('personal_dashboard'))
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    if user.get('points', 0) < reward.get('cost', 0):
        flash("You don't have enough points for this reward.", "error")
        return redirect(url_for('personal_dashboard'))
    users_collection.update_one({'_id': ObjectId(current_user.id)}, {'$inc': {'points': -reward['cost']}})
    rewards_collection.insert_one({
        'family_id': fam_oid, 'requested_by_id': ObjectId(current_user.id),
        'reward_name': reward['name'], 'cost': reward['cost'], 'status': 'pending',
        'requested_at': now_est(), 'resolved_at': None, 'resolved_by_id': None
    })
    flash(f"You've successfully requested '{reward['name']}'! Awaiting parent approval.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/reward/store/add', methods=['POST'])
@login_required
def add_store_reward():
    if current_user.role != 'parent':
        return redirect(url_for('personal_dashboard'))
    name = request.form.get('name', '').strip()
    cost_str = request.form.get('cost', '')
    if not name or not cost_str:
        flash("Reward name and cost are required.", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        cost = int(cost_str)
        if cost <= 0: raise ValueError("Cost must be positive.")
    except ValueError as e:
        flash(f"Invalid point cost: {e}", "error")
        return redirect(url_for('personal_dashboard'))
    store_rewards_collection.insert_one({
        'name': name, 'cost': cost, 'family_id': ObjectId(current_user.family_id), 'created_at': now_est()
    })
    flash(f"Reward '{name}' added to the store.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/reward/store/delete/<reward_id>')
@login_required
def delete_store_reward(reward_id):
    if current_user.role != 'parent':
        return redirect(url_for('personal_dashboard'))
    try:
        reward_oid = ObjectId(reward_id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid reward ID format.", "error")
        return redirect(url_for('personal_dashboard'))
    result = store_rewards_collection.delete_one({'_id': reward_oid, 'family_id': fam_oid})
    if result.deleted_count > 0:
        flash("Reward removed from the store.", "success")
    else:
        flash("Could not find the reward to delete.", "error")
    return redirect(url_for('personal_dashboard'))

################################################################################
# 10. EVENT / TASK MANAGEMENT ROUTES
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
    name = request.form.get('name', '').strip()
    points_str = request.form.get('points', '')
    if not name or not points_str:
        flash("Task Name and Points are required.", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        points = int(points_str)
        if points <= 0: raise ValueError("Points must be positive.")
    except ValueError as e:
        flash(f"Invalid points value: {e}", "error")
        return redirect(url_for('personal_dashboard'))
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'_id': 1}))
    if not children:
        flash("There are no children in the family to assign tasks to.", "warning")
        return redirect(url_for('personal_dashboard'))
    child_ids = [str(c['_id']) for c in children]
    try:
        input_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
        start_date = start_of_day_est(input_date)
    except ValueError:
        flash("Invalid due date provided.", "error")
        return redirect(url_for('personal_dashboard'))
    family_oid = ObjectId(current_user.family_id)
    all_events_to_insert = []
    base_doc_template = {
        'name': name, 'description': "", 'points': points,
        'type': task_type, 'family_id': family_oid, 'status': 'assigned', 'created_at': now_est()
    }
    if task_type == 'habit':
        base_doc_template.update({'streak': 0, 'last_completed': None})
    if recurrence == 'none':
        assignees = child_ids if assigned_to_value == "__ALL__" else ([next(itertools.cycle(child_ids))] if assigned_to_value == "__ROUND_ROBIN__" else [assigned_to_value])
        for user_id in assignees:
            if user_id not in child_ids: continue
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
            assignees = child_ids if assigned_to_value == "__ALL__" else ([next(child_cycler)] if assigned_to_value == "__ROUND_ROBIN__" else [assigned_to_value])
            for user_id in assignees:
                if user_id not in child_ids: continue
                doc = base_doc_template.copy()
                doc['assigned_to'] = ObjectId(user_id)
                doc['due_date'] = current_date
                all_events_to_insert.append(doc)
            current_date += delta
    if all_events_to_insert:
        operations = []
        for doc in all_events_to_insert:
            filter_doc = {
                'family_id': doc['family_id'], 'name': doc['name'],
                'due_date': doc['due_date'], 'assigned_to': doc['assigned_to']
            }
            operations.append(UpdateOne(filter_doc, {'$setOnInsert': doc}, upsert=True))
        try:
            result = events_collection.bulk_write(operations, ordered=False)
            inserted_count = result.upserted_count
            if inserted_count > 0:
                flash(f"{inserted_count} new task(s) scheduled successfully!", 'success')
            else:
                flash("No new tasks scheduled. They might already exist.", 'info')
        except Exception as e:
            flash(f"An error occurred during scheduling: {e}", "error")
    else:
        flash("No tasks were generated based on your input.", "warning")
    return redirect(url_for('personal_dashboard'))

@app.route('/event/edit/<event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
    if current_user.role != 'parent':
        flash("You are not authorized to edit tasks.", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        event_oid = ObjectId(event_id)
        fam_oid = ObjectId(current_user.family_id)
        assigned_to_oid = ObjectId(request.form['assigned_to'])
        points = int(request.form['points'])
        if points <= 0: raise ValueError("Points must be positive.")
        due_date_aware = start_of_day_est(datetime.strptime(request.form['due_date'], '%Y-%m-%d').date())
    except Exception as e:
        flash(f"Invalid input data: {e}", "error")
        return redirect(url_for('manage_plan'))
    if not events_collection.find_one({'_id': event_oid, 'family_id': fam_oid}):
        flash("Task not found.", "error")
        return redirect(url_for('manage_plan'))
    update_data = {
        'name': request.form['name'], 'description': request.form.get('description', ''),
        'points': points, 'assigned_to': assigned_to_oid, 'due_date': due_date_aware
    }
    potential_duplicate = events_collection.find_one({
        'family_id': fam_oid, 'name': update_data['name'], 'due_date': update_data['due_date'],
        'assigned_to': update_data['assigned_to'], '_id': {'$ne': event_oid}
    })
    if potential_duplicate:
        flash("Cannot update task. A duplicate already exists.", "error")
        return redirect(url_for('manage_plan'))
    try:
        events_collection.update_one({'_id': event_oid}, {'$set': update_data})
        flash("Task has been updated.", "success")
    except Exception as e:
        flash(f"An error occurred while updating: {e}", "error")
    return redirect(url_for('manage_plan'))

@app.route('/event/delete/<event_id>')
@login_required
def delete_event(event_id):
    if current_user.role != 'parent':
        return redirect(url_for('personal_dashboard'))
    try:
        event_oid = ObjectId(event_id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid event ID.", "error")
        return redirect(url_for('manage_plan'))
    result = events_collection.delete_one({'_id': event_oid, 'family_id': fam_oid})
    if result.deleted_count > 0:
        flash("Task has been deleted.", "success")
    else:
        flash("Task not found or permission denied.", "error")
    return redirect(url_for('manage_plan'))

@app.route('/event/complete/<event_id>')
@login_required
def complete_event(event_id):
    if current_user.role != 'child':
        return redirect(url_for('personal_dashboard'))
    try:
        event_oid = ObjectId(event_id)
        user_oid = ObjectId(current_user.id)
    except:
        flash("Invalid event ID.", "error")
        return redirect(url_for('personal_dashboard'))
    result = events_collection.update_one(
        {'_id': event_oid, 'assigned_to': user_oid, 'type': 'chore', 'status': 'assigned'},
        {'$set': {'status': 'completed', 'completed_at': now_est()}}
    )
    if result.modified_count > 0:
        flash('Chore marked as complete! Awaiting approval.', 'success')
    else:
        flash('Could not mark chore as complete.', 'warning')
    return redirect(url_for('personal_dashboard'))

@app.route('/event/habit/checkin/<event_id>')
@login_required
def checkin_habit(event_id):
    if current_user.role != 'child':
        return redirect(url_for('personal_dashboard'))
    try:
        event_oid = ObjectId(event_id)
        user_oid = ObjectId(current_user.id)
    except:
        flash("Invalid event ID.", "error")
        return redirect(url_for('personal_dashboard'))
    habit = events_collection.find_one({'_id': event_oid, 'assigned_to': user_oid, 'type': 'habit'})
    if not habit:
        flash("Habit not found or not assigned to you.", "error")
        return redirect(url_for('personal_dashboard'))
    if habit.get('status') in ['missed', 'forgiven']:
        flash("Cannot check in a missed or forgiven habit.", "error")
        return redirect(url_for('personal_dashboard'))
    today = today_est()
    last_completed = habit.get('last_completed')
    last_completed_date_est = last_completed.astimezone(TIMEZONE).date() if last_completed else None
    if last_completed_date_est and last_completed_date_est == today:
        flash('You have already checked in today.', 'info')
        return redirect(url_for('personal_dashboard'))
    new_streak = 1
    if last_completed_date_est and last_completed_date_est == today - timedelta(days=1):
        new_streak = habit.get('streak', 0) + 1
    points_earned = habit.get('points', 0)
    events_collection.update_one(
        {'_id': event_oid},
        {'$set': {'last_completed': now_est(), 'streak': new_streak}}
    )
    users_collection.update_one(
        {'_id': user_oid},
        {'$inc': {'points': points_earned, 'lifetime_points': points_earned}}
    )
    flash(f"Habit checked in! You earned {points_earned} points. Streak is now {new_streak}.", 'success')
    return redirect(url_for('personal_dashboard'))

@app.route('/event/approve/<event_id>')
@login_required
def approve_event(event_id):
    if current_user.role != 'parent':
        return redirect(url_for('personal_dashboard'))
    try:
        event_oid = ObjectId(event_id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid event ID.", "error")
        return redirect(url_for('personal_dashboard'))
    event_to_approve = events_collection.find_one({'_id': event_oid, 'family_id': fam_oid, 'status': 'completed'})
    if not event_to_approve:
        flash("Task not found or is not awaiting approval.", "error")
        return redirect(url_for('personal_dashboard'))
    points_to_award = event_to_approve.get('points', 0)
    result = events_collection.update_one({'_id': event_oid}, {'$set': {'status': 'approved', 'approved_at': now_est()}})
    if result.modified_count > 0 and event_to_approve.get('assigned_to') and points_to_award > 0:
        users_collection.update_one(
            {'_id': event_to_approve['assigned_to']},
            {'$inc': {'points': points_to_award, 'lifetime_points': points_to_award}}
        )
        flash(f"Task approved! {points_to_award} points awarded.", 'success')
    elif result.modified_count > 0:
        flash(f"Task approved! (No points awarded).", 'success')
    else:
        flash("Failed to update task status.", 'error')
    return redirect(url_for('personal_dashboard'))

@app.route('/event/bulk_approve', methods=['POST'])
@login_required
def bulk_approve_events():
    if current_user.role != 'parent':
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    event_ids_str = data.get('event_ids', [])
    if not isinstance(event_ids_str, list) or not event_ids_str:
        return jsonify({"status": "warning", "message": "No event IDs provided"}), 200
    try:
        event_ids_obj = [ObjectId(eid) for eid in event_ids_str]
        fam_oid = ObjectId(current_user.family_id)
    except:
        return jsonify({"error": "Invalid event ID format found in list"}), 400
    events_to_approve = list(events_collection.find({'_id': {'$in': event_ids_obj}, 'family_id': fam_oid, 'status': 'completed'}))
    if not events_to_approve:
        return jsonify({"status": "warning", "message": "No valid tasks found awaiting approval."}), 200
    points_to_award = defaultdict(int)
    valid_event_ids_to_update = []
    now = now_est()
    for event in events_to_approve:
        award = event.get('points', 0)
        if award > 0 and event.get('assigned_to'):
            points_to_award[event['assigned_to']] += award
        valid_event_ids_to_update.append(event['_id'])
    if points_to_award:
        user_updates = [UpdateOne({'_id': uid}, {'$inc': {'points': pts, 'lifetime_points': pts}}) for uid, pts in points_to_award.items()]
        try:
            users_collection.bulk_write(user_updates)
        except Exception as e:
            print(f"Error during bulk user update: {e}")
    if valid_event_ids_to_update:
        try:
            event_updates_result = events_collection.update_many(
                {'_id': {'$in': valid_event_ids_to_update}},
                {'$set': {'status': 'approved', 'approved_at': now}}
            )
            approved_count = event_updates_result.modified_count
            flash(f"{approved_count} task(s) approved!", "success")
            return jsonify({"status": "success", "approved_count": approved_count}), 200
        except Exception as e:
            print(f"Error during bulk event update: {e}")
            flash("An error occurred updating task statuses.", "error")
            return jsonify({"error": "Failed to update all event statuses"}), 500
    return jsonify({"status": "success", "approved_count": 0}), 200




@app.route('/challenge/claim/<string:challenge_id>')
@login_required
def claim_challenge(challenge_id):
    if current_user.role != 'child':
        flash("Only children can claim challenges.", "error")
        return redirect(url_for('personal_dashboard'))
    
    try:
        challenge_oid = ObjectId(challenge_id)
        user_oid = ObjectId(current_user.id)
    except Exception:
        flash("Invalid challenge ID.", "error")
        return redirect(url_for('personal_dashboard'))

    # Find the challenge and ensure it's 'open'
    challenge_to_claim = challenges_collection.find_one({
        '_id': challenge_oid,
        'family_id': ObjectId(current_user.family_id),
        'status': 'open'
    })

    if not challenge_to_claim:
        flash("This challenge is not available to claim.", "warning")
        return redirect(url_for('personal_dashboard'))
    
    # Claim the challenge
    challenges_collection.update_one(
        {'_id': challenge_oid},
        {'$set': {
            'status': 'in_progress',
            'claimed_by_id': user_oid,
            'claimed_at': now_est()
        }}
    )
    
    flash(f"You have claimed the challenge: '{challenge_to_claim.get('title')}'!", "success")
    return redirect(url_for('personal_dashboard'))


@app.route('/challenge/complete/<string:challenge_id>')
@login_required
def complete_challenge(challenge_id):
    if current_user.role != 'child':
        flash("Only children can complete challenges.", "error")
        return redirect(url_for('personal_dashboard'))

    try:
        challenge_oid = ObjectId(challenge_id)
        user_oid = ObjectId(current_user.id)
    except Exception:
        flash("Invalid challenge ID.", "error")
        return redirect(url_for('personal_dashboard'))

    # Find the challenge and ensure it was claimed by the current user
    challenge_to_complete = challenges_collection.find_one({
        '_id': challenge_oid,
        'family_id': ObjectId(current_user.family_id),
        'status': 'in_progress',
        'claimed_by_id': user_oid
    })

    if not challenge_to_complete:
        flash("This challenge is not ready to be completed by you.", "warning")
        return redirect(url_for('personal_dashboard'))

    points_to_award = challenge_to_complete.get('points', 0)

    # 1. Mark the challenge as completed
    challenges_collection.update_one(
        {'_id': challenge_oid},
        {'$set': {
            'status': 'completed',
            'completed_at': now_est()
        }}
    )
    
    # 2. Award the points to the user
    if points_to_award > 0:
        users_collection.update_one(
            {'_id': user_oid},
            {'$inc': {
                'points': points_to_award,
                'lifetime_points': points_to_award
            }}
        )
    
    flash(f"Challenge completed! You earned {points_to_award} points!", "success")
    return redirect(url_for('personal_dashboard'))




################################################################################
# 11. PLAN MANAGEMENT ROUTES
################################################################################

@app.route('/manage-plan')
@login_required
def manage_plan():
    if current_user.role != 'parent':
        flash("You don't have permission to view this page.", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid family ID.", "error")
        return redirect(url_for('personal_dashboard'))
    active_plan = famjam_plans_collection.find_one({'family_id': fam_oid, 'status': 'active'})
    if not active_plan:
        flash("No active FamJam plan found. Generate one from the dashboard!", "info")
        return redirect(url_for('personal_dashboard'))
    sort_by = request.args.get('sort_by', 'due_date')
    order_str = request.args.get('order', 'asc')
    order = ASCENDING if order_str == 'asc' else DESCENDING
    plan_start_utc = active_plan['start_date'].astimezone(pytz.utc)
    plan_end_utc = active_plan['end_date'].astimezone(pytz.utc) + timedelta(days=1)
    filter_date_str = request.args.get('filter_date')
    date_filter = {}
    if filter_date_str:
        try:
            filter_date_obj = datetime.strptime(filter_date_str, '%Y-%m-%d').date()
            filter_start_aware = start_of_day_est(filter_date_obj).astimezone(pytz.utc)
            filter_end_aware = filter_start_aware + timedelta(days=1)
            date_filter = {'due_date': {'$gte': filter_start_aware, '$lt': filter_end_aware}}
        except ValueError:
            flash("Invalid filter date format.", "warning")
    tasks_cursor = events_collection.find({
        'family_id': fam_oid, 'due_date': {'$gte': plan_start_utc, '$lt': plan_end_utc}, **date_filter
    }).sort(sort_by, order)
    family_members_raw = list(users_collection.find({'family_id': current_user.family_id}))
    family_members = []
    member_map = {}
    for member in family_members_raw:
        member_id_str = str(member['_id'])
        member_map[member_id_str] = member.get('username', 'N/A')
        if member.get('role') == 'child':
            member['_id'] = member_id_str
            family_members.append(member)
    tasks = []
    for task in tasks_cursor:
        task['_id'] = str(task['_id'])
        task_assigned_to_str = str(task.get('assigned_to'))
        task['assigned_to_username'] = member_map.get(task_assigned_to_str, 'N/A')
        task['assigned_to'] = task_assigned_to_str
        task['json_string'] = json_util.dumps(task)
        tasks.append(task)
    # Assuming manage_plan.html template exists
    return render_template(
        'manage_plan.html', plan=active_plan, tasks=tasks,
        family_members=family_members, current_sort={'by': sort_by, 'order': order_str},
        TIMEZONE=TIMEZONE_NAME, # Pass the name string (for base.html)
        TIMEZONE_OBJ=TIMEZONE    # Pass the pytz object (for Jinja)
    )

@app.route('/plan/add_task/<plan_id>', methods=['POST'])
@login_required
def add_task_to_plan(plan_id):
    if current_user.role != 'parent':
        flash("Unauthorized access.", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        plan_oid = ObjectId(plan_id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid plan ID.", "error")
        return redirect(url_for('personal_dashboard'))
    plan = famjam_plans_collection.find_one({'_id': plan_oid, 'family_id': fam_oid})
    if not plan:
        flash("Plan not found.", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        name = request.form['name'].strip()
        points = int(request.form['points'])
        assigned_to_oid = ObjectId(request.form['assigned_to'])
        due_date_str = request.form['due_date']
        if not name or points <= 0 or not due_date_str:
            raise ValueError("Name, positive points, assignee, and due date required.")
        due_date_aware = start_of_day_est(datetime.strptime(due_date_str, '%Y-%m-%d').date())
        if not users_collection.find_one({'_id': assigned_to_oid, 'family_id': str(fam_oid), 'role': 'child'}):
             raise ValueError("Invalid assignee selected.")
    except Exception as e:
        flash(f"Error in task data: {e}", 'error')
        return redirect(url_for('manage_plan'))
    plan_start = plan['start_date']
    plan_end = plan['end_date']
    if not (plan_start <= due_date_aware <= plan_end):
        flash(f"Warning: The due date is outside the active plan's range. Task added anyway.", 'warning')
    new_event_doc = {
        'name': name, 'description': request.form.get('description', ''), 'points': points,
        'type': 'chore', 'family_id': fam_oid, 'status': 'assigned', 'created_at': now_est(),
        'assigned_to': assigned_to_oid, 'due_date': due_date_aware, 'source_type': 'manual'
    }
    filter_doc = {
        'family_id': new_event_doc['family_id'], 'name': new_event_doc['name'],
        'due_date': new_event_doc['due_date'], 'assigned_to': new_event_doc['assigned_to']
    }
    if events_collection.find_one(filter_doc):
        flash(f"Task '{name}' for this user on this date already exists.", 'error')
    else:
        try:
            events_collection.insert_one(new_event_doc)
            flash(f"Task '{name}' was added.", 'success')
        except Exception as e:
            flash(f"Error adding task: {e}", 'error')
    return redirect(url_for('manage_plan'))

@app.route('/plan/edit_name/<plan_id>', methods=['POST'])
@login_required
def edit_plan_name(plan_id):
    if current_user.role != 'parent':
        flash("Unauthorized", "error")
        return redirect(url_for('personal_dashboard'))
    new_name = request.form.get('plan_name', '').strip()
    if not new_name:
        flash("Plan name cannot be empty.", "error")
        return redirect(url_for('manage_plan'))
    try:
        plan_oid = ObjectId(plan_id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid plan ID.", "error")
        return redirect(url_for('manage_plan'))
    result = famjam_plans_collection.update_one(
        {'_id': plan_oid, 'family_id': fam_oid},
        {'$set': {'plan_data.plan_name': new_name}}
    )
    if result.modified_count > 0:
        flash("Plan name updated.", "success")
    else:
        flash("Plan not found or name was not changed.", "warning")
    return redirect(url_for('manage_plan'))

################################################################################
# 12. CONTEXT, UTILITY, & PERSONAL ROUTES
################################################################################

@app.context_processor
def inject_global_vars():
    if not current_user.is_authenticated:
        return {}
    try:
        user_oid = ObjectId(current_user.id)
        fam_oid_str = current_user.family_id
        fam_oid = ObjectId(fam_oid_str)
    except:
        logout_user()
        return {}
    family_members = list(users_collection.find({'family_id': fam_oid_str}))
    personal_notes = list(notes_collection.find({'user_id': user_oid}).sort('created_at', DESCENDING))
    personal_todos = list(personal_todos_collection.find({'user_id': user_oid}).sort([('is_done', ASCENDING), ('created_at', DESCENDING)]))
    parent = {}
    family_doc = families_collection.find_one({'_id': fam_oid})
    primary_parent_oid = family_doc['parent_ids'][0] if family_doc and family_doc.get('parent_ids') else None
    for member in family_members:
        member['_id'] = str(member['_id'])
        if primary_parent_oid and member['_id'] == str(primary_parent_oid):
            parent = member
    unread_messages_exist = direct_messages_collection.find_one({'recipient_id': user_oid, 'is_read': False}) is not None
    return {
        'family_members': family_members, 'parent': parent, 'unread_messages_exist': unread_messages_exist,
        'personal_notes': personal_notes, 'personal_todos': personal_todos,
        'TIMEZONE': TIMEZONE_NAME
    }

@app.route('/child/reset-password/<child_id>', methods=['POST'])
@login_required
def reset_child_password(child_id):
    if current_user.role != 'parent':
        flash('You do not have permission.', 'error')
        return redirect(url_for('personal_dashboard'))
    new_password = request.form.get('new_password')
    if not new_password or len(new_password) < 6:
        flash('New password must be at least 6 characters.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))
    try:
        child_oid = ObjectId(child_id)
    except:
        flash('Invalid child ID.', 'error')
        return redirect(url_for('personal_dashboard'))
    child = users_collection.find_one({'_id': child_oid, 'family_id': current_user.family_id, 'role': 'child'})
    if not child:
        flash('Child not found in your family.', 'error')
        return redirect(url_for('personal_dashboard'))
    hashed_pw = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users_collection.update_one({'_id': child_oid}, {'$set': {'password_hash': hashed_pw}})
    flash(f"Password for {child.get('username')} has been reset.", 'success')
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/child/edit/<child_id>', methods=['POST'])
@login_required
def edit_child(child_id):
    if current_user.role != 'parent':
        flash("Unauthorized", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        child_oid = ObjectId(child_id)
    except:
        flash("Invalid child ID", "error")
        return redirect(url_for('personal_dashboard'))
    child = users_collection.find_one({'_id': child_oid, 'family_id': current_user.family_id, 'role': 'child'})
    if not child:
        flash("Child not found", "error")
        return redirect(url_for('personal_dashboard'))
    update_data = {}
    new_username = request.form.get('username', '').strip()
    if new_username and new_username != child.get('username'):
        if users_collection.find_one({'username': new_username, 'family_id': current_user.family_id, '_id': {'$ne': child_oid}}):
            flash('That username is already taken in your family.', 'error')
            return redirect(request.referrer or url_for('personal_dashboard'))
        update_data['username'] = new_username
    if update_data:
        users_collection.update_one({'_id': child_oid}, {'$set': update_data})
        flash('Child username updated.', 'success')
    else:
        flash('No changes detected.', 'info')
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/child/remove/<child_id>')
@login_required
def remove_child(child_id):
    if current_user.role != 'parent':
        flash("Unauthorized", "error")
        return redirect(url_for('personal_dashboard'))
    try:
        child_oid = ObjectId(child_id)
    except:
        flash("Invalid child ID", "error")
        return redirect(url_for('personal_dashboard'))
    child = users_collection.find_one({'_id': child_oid, 'family_id': current_user.family_id, 'role': 'child'})
    if child:
        users_collection.delete_one({'_id': child_oid})
        events_collection.delete_many({'assigned_to': child_oid})
        rewards_collection.delete_many({'requested_by_id': child_oid})
        moods_collection.delete_many({'user_id': child_oid})
        notes_collection.delete_many({'user_id': child_oid})
        personal_todos_collection.delete_many({'user_id': child_oid})
        challenges_collection.update_many({'claimed_by_id': child_oid}, {'$set': {'status': 'open', 'claimed_by_id': None, 'claimed_at': None}})
        flash(f"{child.get('username')} and all their data have been removed.", 'success')
    else:
        flash('Child not found.', 'error')
    return redirect(request.referrer or url_for('personal_dashboard'))

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
        'family_id': current_user.family_id, 'points': 0, 'lifetime_points': 0, 'cash_balance': 0.0
    })
    flash(f"Child account for '{username}' created!", 'success')
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/parent/create_another_parent', methods=['POST'])
@login_required
def create_another_parent():
    if current_user.role != 'parent':
        flash("Unauthorized.", "error")
        return redirect(url_for('personal_dashboard'))
    email = request.form.get('email', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not email or not username or len(password) < 8:
        flash('Email, Username, and a password of at least 8 characters are required.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))
    if users_collection.find_one({'$or': [{'email': email}, {'username': username, 'family_id': current_user.family_id}]}):
        flash('That email is already in use, or the username is taken within your family.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))
    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    new_parent_id = users_collection.insert_one({
        'email': email, 'username': username, 'password_hash': hashed_pw, 'role': 'parent',
        'family_id': current_user.family_id, 'points': 0, 'lifetime_points': 0, 'cash_balance': 0.0
    }).inserted_id
    families_collection.update_one({'_id': ObjectId(current_user.family_id)}, {'$push': {'parent_ids': new_parent_id}})
    flash(f"Parent account for '{username}' created!", 'success')
    return redirect(request.referrer or url_for('personal_dashboard'))

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
        if end_date < now_est():
             flash("Cannot set a timer for a past date.", "error")
             return redirect(url_for('family_dashboard'))
    except ValueError:
        flash("Invalid date format.", "error")
        return redirect(url_for('family_dashboard'))
    timers_collection.insert_one({
        'name': timer_name, 'end_date': end_date, 'family_id': ObjectId(current_user.family_id),
        'created_by': ObjectId(current_user.id), 'created_at': now_est()
    })
    flash("Timer created!", "success")
    return redirect(url_for('family_dashboard'))

@app.route('/timer/delete/<timer_id>')
@login_required
def delete_timer(timer_id):
    try:
        timer_oid = ObjectId(timer_id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid timer ID.", "error")
        return redirect(url_for('family_dashboard'))
    timer = timers_collection.find_one({'_id': timer_oid, 'family_id': fam_oid})
    if not timer:
        flash("Timer not found.", "error")
    elif str(timer.get('created_by')) == current_user.id or current_user.role == 'parent':
        timers_collection.delete_one({'_id': timer_oid})
        flash("Timer deleted.", "success")
    else:
        flash("You don't have permission to delete this timer.", "error")
    return redirect(url_for('family_dashboard'))

@app.route('/account/delete', methods=['GET'])
@login_required
def delete_account():
    try:
        user_oid = ObjectId(current_user.id)
        fam_oid_str = current_user.family_id
        fam_oid = ObjectId(fam_oid_str)
        if current_user.role == 'parent':
            family = families_collection.find_one({'_id': fam_oid})
            parent_ids = family.get('parent_ids', [])
            if user_oid in parent_ids:
                parent_ids.remove(user_oid)
            if not parent_ids:
                print(f"Deleting entire family {fam_oid_str} as last parent left.")
                users_collection.delete_many({'family_id': fam_oid_str})
                events_collection.delete_many({'family_id': fam_oid})
                rewards_collection.delete_many({'family_id': fam_oid})
                moods_collection.delete_many({'family_id': fam_oid})
                famjam_plans_collection.delete_many({'family_id': fam_oid})
                timers_collection.delete_many({'family_id': fam_oid})
                challenges_collection.delete_many({'family_id': fam_oid})
                direct_messages_collection.delete_many({'family_id': fam_oid})
                store_rewards_collection.delete_many({'family_id': fam_oid})
                families_collection.delete_one({'_id': fam_oid})
                notes_collection.delete_many({'user_id': user_oid})
                personal_todos_collection.delete_many({'user_id': user_oid})
            else:
                families_collection.update_one({'_id': fam_oid}, {'$set': {'parent_ids': parent_ids}})
                users_collection.delete_one({'_id': user_oid})
                notes_collection.delete_many({'user_id': user_oid})
                personal_todos_collection.delete_many({'user_id': user_oid})
        elif current_user.role == 'child':
            users_collection.delete_one({'_id': user_oid})
            events_collection.delete_many({'assigned_to': user_oid})
            rewards_collection.delete_many({'requested_by_id': user_oid})
            moods_collection.delete_many({'user_id': user_oid})
            notes_collection.delete_many({'user_id': user_oid})
            personal_todos_collection.delete_many({'user_id': user_oid})
            challenges_collection.update_many({'claimed_by_id': user_oid}, {'$set': {'status': 'open', 'claimed_by_id': None, 'claimed_at': None}})
        logout_user()
        flash("Your account and all associated data have been permanently deleted.", "success")
        return redirect(url_for('login'))
    except Exception as e:
        print(f"Error deleting account: {e}")
        flash("An error occurred while trying to delete your account.", "error")
        return redirect(url_for('personal_dashboard'))

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
    try:
        note_oid = ObjectId(note_id)
        user_oid = ObjectId(current_user.id)
    except:
        flash("Invalid note ID.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))
    notes_collection.delete_one({'_id': note_oid, 'user_id': user_oid})
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
    try:
        todo_oid = ObjectId(todo_id)
        user_oid = ObjectId(current_user.id)
    except:
        flash("Invalid todo ID.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))
    personal_todos_collection.delete_one({'_id': todo_oid, 'user_id': user_oid})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/todo/toggle/<todo_id>')
@login_required
def toggle_todo(todo_id):
    try:
        todo_oid = ObjectId(todo_id)
        user_oid = ObjectId(current_user.id)
    except:
        flash("Invalid todo ID.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))
    todo = personal_todos_collection.find_one({'_id': todo_oid, 'user_id': user_oid})
    if todo:
        new_status = not todo.get('is_done', False)
        personal_todos_collection.update_one({'_id': todo_oid}, {'$set': {'is_done': new_status}})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/message/send', methods=['POST'])
@login_required
def send_message():
    message_content = request.form.get('message_content', '').strip()
    recipient_id_str = request.form.get('recipient_id', '').strip()
    if not message_content or not recipient_id_str:
        flash("Recipient and message content are required.", "error")
        if request.headers.get('Accept') == 'application/json':
            return jsonify({"status": "error", "message": "Recipient and message required."}), 400
        return redirect(request.referrer or url_for('personal_dashboard'))
    try:
        recipient_oid = ObjectId(recipient_id_str)
        user_oid = ObjectId(current_user.id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        flash("Invalid recipient ID.", "error")
        if request.headers.get('Accept') == 'application/json':
            return jsonify({"status": "error", "message": "Invalid recipient ID."}), 400
        return redirect(request.referrer or url_for('personal_dashboard'))
    recipient = users_collection.find_one({'_id': recipient_oid, 'family_id': current_user.family_id})
    if not recipient:
        flash("Invalid recipient or recipient not in your family.", "error")
        if request.headers.get('Accept') == 'application/json':
            return jsonify({"status": "error", "message": "Invalid recipient."}), 400
        return redirect(request.referrer or url_for('personal_dashboard'))
    if recipient_oid == user_oid:
        flash("You cannot send a message to yourself.", "error")
        if request.headers.get('Accept') == 'application/json':
            return jsonify({"status": "error", "message": "Cannot send to self."}), 400
        return redirect(request.referrer or url_for('personal_dashboard'))
    direct_messages_collection.insert_one({
        "family_id": fam_oid, "sender_id": user_oid,
        "sender_username": current_user.username, "recipient_id": recipient_oid,
        "recipient_username": recipient.get('username', 'Unknown'),
        "message_content": message_content, "sent_at": now_est(), "is_read": False
    })
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"status": "success"})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/api/messages')
@login_required
def get_direct_messages():
    try:
        current_user_id = ObjectId(current_user.id)
        fam_oid = ObjectId(current_user.family_id)
    except:
        return jsonify({"error": "Invalid user or family ID"}), 400
    messages_cursor = direct_messages_collection.find({
        'family_id': fam_oid,
        '$or': [{'sender_id': current_user_id}, {'recipient_id': current_user_id}]
    }).sort('sent_at', ASCENDING)
    return Response(json_util.dumps(list(messages_cursor)), mimetype='application/json')

@app.route('/api/message/mark-read', methods=['POST'])
@login_required
def mark_messages_read():
    data = request.get_json()
    message_ids_str = data.get('message_ids', [])
    if not isinstance(message_ids_str, list) or not message_ids_str:
        return jsonify({"status": "success", "modified_count": 0})
    try:
        message_ids_obj = [ObjectId(msg_id) for msg_id in message_ids_str]
        user_oid = ObjectId(current_user.id)
    except:
        return jsonify({"error": "Invalid message ID format found in list."}), 400
    result = direct_messages_collection.update_many(
        {'_id': {'$in': message_ids_obj}, 'recipient_id': user_oid, 'is_read': False},
        {'$set': {'is_read': True}}
    )
    return jsonify({"status": "success", "modified_count": result.modified_count})

################################################################################
# 12. API ROUTES
################################################################################

@app.route('/api/events')
@login_required
def api_events():
    try:
        fam_oid = ObjectId(current_user.family_id)
    except:
        return jsonify({"error": "Invalid family ID"}), 400
    child_colors = ['#ef4444', '#f97316', '#eab308', '#84cc16', '#22c55e', '#14b8a6', '#06b6d4', '#6366f1', '#a855f7', '#d946ef']
    fam_members = list(users_collection.find({'family_id': current_user.family_id}))
    member_map = {str(m['_id']): m['username'] for m in fam_members}
    child_color_map = {str(c['_id']): child_colors[i % len(child_colors)] for i, c in enumerate(m for m in fam_members if m.get('role') == 'child')}
    query = {'family_id': fam_oid}
    if (search := request.args.get('search')):
        query['name'] = regex.Regex(search, 'i')
    if (member_id_str := request.args.get('member')):
        try: query['assigned_to'] = ObjectId(member_id_str)
        except: pass
    if (etype := request.args.get('type')) and etype in ['chore', 'habit']:
        query['type'] = etype
    start_param = request.args.get('start')
    end_param = request.args.get('end')
    if start_param and end_param:
        try:
            start_date_utc = datetime.fromisoformat(start_param.replace('Z', '+00:00')).astimezone(pytz.utc)
            end_date_utc = datetime.fromisoformat(end_param.replace('Z', '+00:00')).astimezone(pytz.utc)
            query['due_date'] = {'$gte': start_date_utc, '$lt': end_date_utc}
        except ValueError: pass
    cursor = events_collection.find(query)
    calendar_events = []
    today = today_est()
    for e in cursor:
        assigned_to_id_str = str(e.get('assigned_to'))
        can_checkin = False
        due_date_est = e.get('due_date').astimezone(TIMEZONE).date() if e.get('due_date') else None
        is_due_today = (due_date_est == today) if due_date_est else False
        if e.get('type') == 'habit' and is_due_today and e.get('status') not in ['missed', 'forgiven']: # Added forgiven check
            last_completed_date_est = e.get('last_completed').astimezone(TIMEZONE).date() if e.get('last_completed') else None
            if not (last_completed_date_est and last_completed_date_est == today):
                can_checkin = True
        start_iso = e.get('due_date').isoformat() if e.get('due_date') else None
        
        # Determine status color/display for calendar
        status = e.get('status')
        title_prefix = f"({status.capitalize()}) " if status in ['missed', 'completed', 'approved', 'forgiven'] else ""
        if status == 'approved':
            color = '#22c55e' # Green
        elif status == 'completed':
            color = '#a855f7' # Purple
        elif status in ['missed', 'forgiven']:
            color = '#6b7280' # Gray
        else: # 'assigned'
            color = child_color_map.get(assigned_to_id_str, '#6b7280')

        calendar_events.append({
            'id': str(e['_id']), 'title': f"{title_prefix}{e['name']}",
            'start': start_iso, 'allDay': True, 'color': color,
            'extendedProps': {
                '_id': str(e['_id']), 'type': e.get('type'), 'description': e.get('description', ''),
                'points': e.get('points'), 'status': status,
                'assignee_name': member_map.get(assigned_to_id_str, 'N/A'),
                'assigned_to': assigned_to_id_str, 'can_checkin': can_checkin,
                'streak': e.get('streak', 0) if e.get('type') == 'habit' else None
            }
        })
    return jsonify(calendar_events)

@app.route('/api/child-day/<child_id>')
@login_required
def api_get_child_day(child_id):
    if current_user.role != 'parent':
        return jsonify({"error": "Unauthorized"}), 403
    try:
        child_user_oid = ObjectId(child_id)
        fam_oid_str = current_user.family_id
        child = users_collection.find_one({'_id': child_user_oid, 'family_id': fam_oid_str})
        if not child:
            return jsonify({"error": "Child not found in your family"}), 404
    except Exception:
        return jsonify({"error": "Invalid child ID"}), 400
    today = today_est()
    # Use naive datetime for querying today's range in MongoDB if due_date is stored naive
    # If due_date is stored timezone-aware (like UTC), query with aware datetimes
    start_of_today_aware_utc = start_of_day_est(today).astimezone(pytz.utc)
    end_of_today_aware_utc = (start_of_day_est(today) + timedelta(days=1)).astimezone(pytz.utc)

    overdue_events = list(events_collection.find({
        'assigned_to': child_user_oid, 'type': 'chore', 'status': 'assigned',
        'due_date': {'$lt': start_of_today_aware_utc} # Use aware UTC for comparison
    }).sort('due_date', ASCENDING))

    todays_events_cursor = events_collection.find({
        'assigned_to': child_user_oid,
        'due_date': {'$gte': start_of_today_aware_utc, '$lt': end_of_today_aware_utc} # Use aware UTC range
    }).sort([('status', ASCENDING), ('type', DESCENDING)])
    todays_events = []
    for event in todays_events_cursor:
        event['can_checkin'] = False
        if event.get('type') == 'habit' and event.get('status') not in ['missed', 'forgiven']: # Added forgiven check
            last_completed = event.get('last_completed')
            last_completed_date = last_completed.astimezone(TIMEZONE).date() if last_completed else None
            if not (last_completed_date and last_completed_date == today):
                event['can_checkin'] = True
        todays_events.append(event)
    return Response(
        json_util.dumps({
            'child_username': child.get('username', 'Unknown'),
            'overdue_events': overdue_events,
            'todays_events': todays_events
        }),
        mimetype='application/json'
    )

@app.route('/api/mood/log', methods=['POST'])
@login_required
def api_mood_log():
    data = request.json
    try:
        entry_date_obj = datetime.strptime(data['date'], '%Y-%m-%d').date()
        entry_date_aware = start_of_day_est(entry_date_obj)
        mood_score = MOOD_EMOJI_TO_SCORE.get(data['emoji'])
        period = data.get('period')
        if not period or not data.get('emoji') or mood_score is None:
            return jsonify({'status': 'error', 'message': 'Missing or invalid mood data.'}), 400
        moods_collection.update_one(
            {'user_id': ObjectId(current_user.id), 'date': entry_date_aware, 'period': period},
            {'$set': {
                'mood_emoji': data['emoji'], 'mood_score': mood_score, 'note': data.get('note', ''),
                'updated_at': now_est()
             },
             '$setOnInsert': {
                'family_id': ObjectId(current_user.family_id), 'created_at': now_est()
             }},
            upsert=True
        )
        return jsonify({'status': 'success'})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid date format.'}), 400
    except Exception as e:
        print(f"Error logging mood: {e}")
        return jsonify({'status': 'error', 'message': 'An internal error occurred.'}), 500

@app.route('/api/mood/personal')
@login_required
def api_mood_personal():
    user_oid = ObjectId(current_user.id)
    if 'date' in request.args and 'period' in request.args:
        try:
            entry_date_obj = datetime.strptime(request.args['date'], '%Y-%m-%d').date()
            entry_date_aware = start_of_day_est(entry_date_obj)
            period = request.args['period']
            entry = moods_collection.find_one({'user_id': user_oid, 'date': entry_date_aware, 'period': period})
            if entry:
                return jsonify({'mood_emoji': entry.get('mood_emoji'), 'note': entry.get('note', '')})
            else:
                return jsonify({}), 200
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
        except Exception as e:
            print(f"Error fetching single mood: {e}")
            return jsonify({'error': 'Could not fetch mood entry'}), 500
    try:
        thirty_days_ago_aware = now_est() - timedelta(days=30)
        mood_entries = list(moods_collection.find({
            'user_id': user_oid,
            'date': {'$gte': start_of_day_est(thirty_days_ago_aware.date())}
        }).sort([('date', ASCENDING), ('period', ASCENDING)])) # Ensure period sort if multiple entries per day
        # Group scores by date for averaging, or structure for sequential display
        # Option 1: Average per day
        daily_scores = defaultdict(lambda: {'total_score': 0, 'count': 0})
        dates_ordered = []
        for entry in mood_entries:
            date_obj = entry['date'].astimezone(TIMEZONE).date()
            date_str = date_obj.strftime('%b %d')
            if date_str not in daily_scores:
                 dates_ordered.append(date_str)
            daily_scores[date_str]['total_score'] += entry['mood_score']
            daily_scores[date_str]['count'] += 1

        chart_labels = dates_ordered
        chart_data = [round(daily_scores[d]['total_score'] / daily_scores[d]['count'], 2) for d in dates_ordered]

        # Option 2: Sequential entries (might be too cluttered for 30 days * 3 periods)
        # chart_labels = [f"{entry['date'].astimezone(TIMEZONE).strftime('%b %d')} {entry['period']}" for entry in mood_entries]
        # chart_data = [entry['mood_score'] for entry in mood_entries]

        return jsonify({'labels': chart_labels, 'data': chart_data})
    except Exception as e:
        print(f"Error fetching mood history: {e}")
        return jsonify({'error': 'Could not fetch mood history'}), 500

@app.route('/api/mood/family')
@login_required
def api_mood_family():
    if current_user.role != 'parent':
        return jsonify({"error": "Unauthorized"}), 403
    try:
        fam_oid = ObjectId(current_user.family_id)
        thirty_days_ago_aware = now_est() - timedelta(days=30)
        start_date_query = start_of_day_est(thirty_days_ago_aware.date())
        match_query = {'family_id': fam_oid, 'date': {'$gte': start_date_query}}
        daily_avg_data = list(moods_collection.aggregate([
            {'$match': match_query},
            {'$group': {'_id': '$date', 'avgScore': {'$avg': '$mood_score'}}},
            {'$sort': {'_id': ASCENDING}}
        ]))
        dist_data = list(moods_collection.aggregate([
            {'$match': match_query},
            {'$group': {'_id': '$mood_emoji', 'count': {'$sum': 1}}},
            {'$sort': {'count': DESCENDING}}
        ]))
        mood_map = {m['emoji']: m for m in MOOD_CONFIG['moods']}
        response_data = {
            'daily_average': {
                'labels': [d['_id'].astimezone(TIMEZONE).strftime('%b %d') for d in daily_avg_data],
                'data': [round(d.get('avgScore', 0), 2) for d in daily_avg_data]
            },
            'distribution': {
                'labels': [f"{d['_id']} ({mood_map.get(d['_id'], {}).get('desc', 'Unknown')})" for d in dist_data],
                'data': [d.get('count', 0) for d in dist_data],
                'colors': [mood_map.get(d['_id'], {}).get('color', '#cccccc') for d in dist_data]
            }
        }
        return jsonify(response_data)
    except Exception as e:
        print(f"Error fetching family mood data: {e}")
        return jsonify({"error": "Could not fetch family mood data"}), 500

@app.route('/api/reward/suggest', methods=['POST'])
@login_required
def suggest_rewards():
    if current_user.role != 'parent' or not openai_client:
        return jsonify({"error": "Not authorized or AI not configured."}), 403

    theme = request.get_json().get('theme', 'general motivation and fun activities')
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'username': 1, '_id': 0}))
    child_names = [c['username'] for c in children]
    child_info = f"for children named {', '.join(child_names)}" if child_names else "for children"

    system_prompt = f"""
    You are an expert in child development and positive reinforcement.
    Generate a JSON object containing ONLY a key "suggested_rewards".
    This key MUST hold an array of 5-7 creative and engaging reward ideas {child_info}.
    The theme for the rewards is: "{theme}".
    Each reward object in the array MUST have ONLY two keys:
    1. "name": A short, descriptive string for the reward (e.g., "Extra 30 Minutes of Screen Time"). Max 50 chars.
    2. "cost": An integer representing the point cost, ranging from 50 to 1000, scaled appropriately to the reward's value.
    Ensure the output is ONLY a valid JSON object starting with {{ and ending with }}. Do not include any text before or after the JSON object.
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
        content = response.choices[0].message.content
        suggestions = json.loads(content)
        if "suggested_rewards" not in suggestions or not isinstance(suggestions["suggested_rewards"], list):
             raise ValueError("AI response missing 'suggested_rewards' array.")
        # Minimal validation on content types
        for reward in suggestions["suggested_rewards"]:
            if not isinstance(reward.get('name'), str) or not isinstance(reward.get('cost'), int):
                raise ValueError("Invalid reward structure in AI response.")

        return jsonify(suggestions)
    except json.JSONDecodeError:
       print(f"AI Response (Invalid JSON): {content}")
       return jsonify({"error": "AI generated invalid JSON response."}), 500
    except Exception as e:
        print(f"Error generating suggestions: {e}")
        return jsonify({"error": f"Failed to generate reward suggestions: {str(e)}"}), 500

@app.route('/api/famjam/suggest', methods=['POST'])
@login_required
def suggest_famjam_plan():
    if current_user.role != 'parent' or not openai_client:
        return jsonify({"error": "Not authorized or AI not configured."}), 403
    goal = request.get_json().get('goal', 'general family teamwork and responsibility')
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'username': 1, '_id': 0}))
    if not children:
        return jsonify({"error": "You need at least one child in the family to create a plan."}), 400
    child_names = [c['username'] for c in children]
    system_prompt = f"""
    Generate ONLY a valid JSON object for a 3-month recurring chore plan for children: {', '.join(child_names)}.
    The family's goal is: "{goal}".
    The JSON object MUST have exactly two top-level keys:
    1.  "plan_name": A creative and relevant string for the plan title.
    2.  "suggested_chores": An array of 5 to 7 distinct chore objects. Each chore object MUST contain ONLY the following keys:
        - "name": A concise string describing the chore (Max 40 chars).
        - "description": A brief string explaining the chore (optional, max 80 chars, can be empty string "").
        - "points": An integer value between 10 and 100.
        - "type": MUST be the string "chore".
        - "recurrence": A string, MUST be one of 'daily', 'weekly', or 'monthly'. Distribute recurrences reasonably.
    Ensure the output is ONLY a valid JSON object starting with {{ and ending with }}.
    """
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate the 3-month chore plan focused on '{goal}'."}
            ]
        )
        content = response.choices[0].message.content
        plan_json = json.loads(content)
        if "plan_name" not in plan_json or "suggested_chores" not in plan_json or not isinstance(plan_json["suggested_chores"], list):
            raise ValueError("AI response structure is invalid.")
        for chore in plan_json["suggested_chores"]:
            if not all(k in chore for k in ['name', 'points', 'type', 'recurrence']) or chore['type'] != 'chore' or not isinstance(chore.get('points'), int):
                raise ValueError("Invalid chore structure in AI response.")
    except json.JSONDecodeError:
        print(f"AI Response (Invalid JSON): {content}")
        return jsonify({"error": "AI generated invalid JSON response."}), 500
    except Exception as e:
        print(f"Error generating plan: {e}")
        return jsonify({"error": f"Failed to generate plan: {str(e)}"}), 500
    today = today_est()
    quarter = (today.month - 1) // 3 + 1
    start_month = (quarter - 1) * 3 + 1
    start_date_aware = start_of_day_est(date(today.year, start_month, 1))
    end_of_quarter_month = start_month + 2
    end_of_quarter_year = today.year
    if end_of_quarter_month == 12:
        end_date_aware = start_of_day_est(date(end_of_quarter_year, 12, 31))
    else:
        next_month_start = date(end_of_quarter_year, end_of_quarter_month + 1, 1)
        end_date_aware = start_of_day_est(next_month_start - timedelta(days=1))
    plan_id = famjam_plans_collection.insert_one({
        'plan_data': plan_json, 'goal': goal, 'family_id': ObjectId(current_user.family_id),
        'status': 'draft', 'start_date': start_date_aware, 'end_date': end_date_aware,
        'created_at': now_est()
    }).inserted_id
    plan_json.update({
        'plan_id': str(plan_id),
        'start_date_str': start_date_aware.strftime('%B %d, %Y'),
        'end_date_str': end_date_aware.strftime('%B %d, %Y')
    })
    return jsonify(plan_json)

@app.route('/api/famjam/apply', methods=['POST'])
@login_required
def apply_famjam_plan():
    if current_user.role != 'parent':
        return jsonify({"error": "Unauthorized"}), 403
    plan_data = request.json
    plan_id_str = plan_data.get('plan_id')
    if not plan_data or 'suggested_chores' not in plan_data or not isinstance(plan_data['suggested_chores'], list) or not plan_id_str:
        return jsonify({'error': 'Invalid plan format received.'}), 400
    try:
        plan_oid = ObjectId(plan_id_str)
        fam_oid = ObjectId(current_user.family_id)
    except:
        return jsonify({'error': 'Invalid plan ID.'}), 400
    plan_in_db = famjam_plans_collection.find_one({'_id': plan_oid, 'family_id': fam_oid})
    if not plan_in_db:
        return jsonify({'error': 'Plan not found.'}), 404
    if plan_in_db['status'] == 'active':
        return jsonify({'error': 'This plan is already active.'}), 400
    famjam_plans_collection.update_many(
        {'family_id': fam_oid, 'status': 'active'},
        {'$set': {'status': 'archived'}}
    )
    update_result = famjam_plans_collection.update_one(
        {'_id': plan_oid},
        {'$set': {
            'status': 'active', 'applied_at': now_est(),
            'plan_data': {'plan_name': plan_data.get('plan_name'), 'suggested_chores': plan_data.get('suggested_chores', [])}
        }}
    )
    if update_result.modified_count == 0:
        return jsonify({'error': 'Failed to activate the plan in the database.'}), 500
    children = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}, {'_id': 1}))
    if not children:
        return jsonify({'status': 'warning', 'message': 'Plan activated, but no children found to schedule tasks for.'})
    child_ids = [str(c['_id']) for c in children]
    child_cycler = itertools.cycle(child_ids)
    current_due_date_aware = plan_in_db['start_date']
    end_date_aware = plan_in_db['end_date']
    bulk_operations = []
    now = now_est()
    for chore_template in plan_data.get('suggested_chores', []):
        name = chore_template.get('name')
        points = int(chore_template.get('points', 0))
        recurrence = chore_template.get('recurrence')
        assigned_to_value = chore_template.get('assigned_to') # This will be the string ID or special value
        description = chore_template.get('description', '')
        delta = {'daily': timedelta(days=1), 'weekly': timedelta(weeks=1), 'monthly': relativedelta(months=1)}.get(recurrence)
        if not delta or not name or points <= 0:
            print(f"Skipping invalid chore template: {chore_template}")
            continue
        loop_date = current_due_date_aware
        while loop_date <= end_date_aware: # Use <= to include end date
            assignees = []
            if assigned_to_value == "__ALL__": assignees = child_ids
            elif assigned_to_value in child_ids: assignees = [assigned_to_value]
            else: assignees = [next(child_cycler)] # Default round robin
            for cid_str in assignees:
                filter_doc = {'family_id': fam_oid, 'name': name, 'due_date': loop_date, 'assigned_to': ObjectId(cid_str)}
                update_doc = {'$setOnInsert': {
                    'description': description, 'points': points, 'type': 'chore',
                    'status': 'assigned', 'created_at': now, 'source_type': 'famjam_plan'
                }}
                bulk_operations.append(UpdateOne(filter_doc, update_doc, upsert=True))
            loop_date += delta
    upserted_count = 0
    if bulk_operations:
        try:
            result = events_collection.bulk_write(bulk_operations, ordered=False)
            upserted_count = result.upserted_count if result else 0
        except Exception as e:
            print(f"Error during bulk event scheduling: {e}")
            return jsonify({'error': f'Plan activated, but failed to schedule chores: {e}'}), 500
    return jsonify({'status': 'success', 'message': f'Plan "{plan_data.get("plan_name", "Plan")}" activated! {upserted_count} new chores scheduled.'})

@app.route('/api/consult-ai', methods=['POST'])
@login_required
def consult_ai():
    if not openai_client:
        return jsonify({"error": "AI service is not configured."}), 503
    try:
        user_oid = ObjectId(current_user.id)
        thirty_days_ago_aware = now_est() - timedelta(days=30)
        mood_entries = list(moods_collection.find({
            'user_id': user_oid,
            'date': {'$gte': start_of_day_est(thirty_days_ago_aware.date())}
        }).sort([('date', ASCENDING), ('period', ASCENDING)]))
    except Exception as e:
        print(f"Error fetching moods for AI: {e}")
        return jsonify({"error": "Could not retrieve mood data."}), 500
    if len(mood_entries) < 5:
        return jsonify({"ai_response": "### Not Enough Data\n\nPlease log at least 5 moods over a few days for a meaningful analysis."}), 200
    mood_log_str = ""
    period_order = {'Morning': 1, 'Afternoon': 2, 'Evening': 3}
    mood_entries.sort(key=lambda x: (x['date'], period_order.get(x.get('period'), 4)))
    for entry in mood_entries:
        mood_desc = next((m['desc'] for m in MOOD_CONFIG['moods'] if m['score'] == entry.get('mood_score')), 'Unknown')
        date_est_str = entry['date'].astimezone(TIMEZONE).strftime('%Y-%m-%d')
        note = entry.get('note', '').strip()
        note_str = f" Note: '{note}'" if note else ""
        mood_log_str += f"- On {date_est_str} ({entry.get('period', 'N/A')}), felt: {mood_desc}.{note_str}\n"
    system_prompt = """
You are 'FAMJAM Insights', a supportive and empathetic AI assistant. Your role is to analyze a user's mood log and provide gentle, constructive feedback.
**Instructions:**
1.  **Disclaimer:** Start *immediately* with: `\n\n**Disclaimer:** I am an AI assistant and cannot provide medical advice. If you are struggling with your mental health, please consult a qualified healthcare professional.\n\n---\n\n`
2.  **Analysis:** Briefly summarize overall mood trends (e.g., predominantly positive, mixed). Mention potential patterns (e.g., lower moods in evenings). Be cautious; use phrases like "It seems like...".
3.  **Acknowledge Notes:** If notes are relevant to a pattern, briefly acknowledge them (e.g., "I noticed you mentioned [topic]..."). Do not over-interpret.
4.  **Suggestions:** Offer 2-3 *general*, actionable, positive well-being suggestions (e.g., mindfulness, journaling, light exercise).
5.  **Encouragement:** End with a short, positive closing statement about self-awareness.
6.  **Format:** Use Markdown (bolding, lists). Keep it concise.
7.  **Focus:** Base analysis *strictly* on the provided log data.
"""
    user_prompt = f"Here is my mood log for the past 30 days. Please analyze it based on your instructions:\n\n{mood_log_str}"
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.6
        )
        ai_response_content = response.choices[0].message.content
        if "**Disclaimer:**" not in ai_response_content:
            ai_response_content = "**Disclaimer:** I am an AI assistant...\n\n---\n\n" + ai_response_content
        return jsonify({"ai_response": ai_response_content})
    except Exception as e:
        print(f"Error consulting AI: {e}")
        return jsonify({"error": f"AI service error: Could not get insights."}), 500

@app.route('/api/suggest-username', methods=['POST'])
def suggest_username():
    if not openai_client:
        return jsonify({"error": "AI service is not configured."}), 503
    name_seed = request.get_json().get('name', '').strip()
    base_prompt = "Generate a JSON object containing ONLY a key 'suggestions'. This key MUST hold an array of 5 unique, creative, and family-friendly usernames suitable for a chore app. Usernames should be alphanumeric, possibly with underscores, max 15 chars. Ensure the output is ONLY a valid JSON object."
    user_content = f"Generate usernames. Base them loosely on the name '{name_seed}' if provided, otherwise generate general ones." if name_seed else "Generate general usernames."
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.8
        )
        content = response.choices[0].message.content
        suggestions_data = json.loads(content)
        if "suggestions" not in suggestions_data or not isinstance(suggestions_data["suggestions"], list):
            raise ValueError("AI response missing 'suggestions' array.")
        valid_suggestions = [s for s in suggestions_data['suggestions'] if isinstance(s, str) and 1 < len(s) <= 15 and s.replace('_', '').isalnum()][:5]
        return jsonify({"suggestions": valid_suggestions})
    except json.JSONDecodeError:
        print(f"AI Username Response (Invalid JSON): {content}")
        return jsonify({"error": "AI generated invalid JSON response."}), 500
    except Exception as e:
        print(f"Error suggesting username: {e}")
        return jsonify({"error": f"Could not generate username suggestions: {str(e)}"}), 500

@app.route('/child/reset-points/<string:child_id>', methods=['POST'])
@login_required
def reset_child_points(child_id):
    """
    Allows a parent to reset a child's current (spendable) points to 0.
    This does not affect lifetime_points or cash_balance.
    """
    # 1. Check if the current user is a parent
    if current_user.role != 'parent':
        flash('You do not have permission to perform this action.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 2. Validate the Child's ObjectId
    try:
        child_oid = ObjectId(child_id)
    except Exception:
        flash('Invalid child ID format.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 3. Find the child and ensure they belong to the parent's family
    child = users_collection.find_one({
        '_id': child_oid,
        'family_id': current_user.family_id,
        'role': 'child'
    })

    if not child:
        flash('Child not found in your family.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 4. Perform the update
    try:
        users_collection.update_one(
            {'_id': child_oid},
            {'$set': {'points': 0}}  # Set spendable points to 0
        )
        flash(f"Current points for {child.get('username')} have been successfully reset to 0.", 'success')
    except Exception as e:
        print(f"Error resetting points for child {child_id}: {e}")
        flash('An error occurred while trying to reset points.', 'error')

    # 5. Redirect back to the previous page
    return redirect(request.referrer or url_for('personal_dashboard'))

# --- NEW ROUTE ---
@app.route('/child/forgive-missed/<string:child_id>', methods=['POST'])
@login_required
def forgive_child_missed_tasks(child_id):
    """
    Allows a parent to change all of a child's 'missed' tasks to 'forgiven'.
    This provides a "fresh start" for weekly stats without restoring points.
    """
    # 1. Check if the current user is a parent
    if current_user.role != 'parent':
        flash('You do not have permission to perform this action.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 2. Validate the Child's ObjectId
    try:
        child_oid = ObjectId(child_id)
    except Exception:
        flash('Invalid child ID format.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 3. Find the child and ensure they belong to the parent's family
    child = users_collection.find_one({
        '_id': child_oid,
        'family_id': current_user.family_id,
        'role': 'child'
    })

    if not child:
        flash('Child not found in your family.', 'error')
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 4. Perform the update: Find all 'missed' tasks and set to 'forgiven'
    try:
        result = events_collection.update_many(
            {'assigned_to': child_oid, 'status': 'missed'},
            {'$set': {'status': 'forgiven', 'forgiven_at': now_est()}}
        )
        flash(f"All ({result.modified_count}) missed tasks for {child.get('username')} have been forgiven.", 'success')
    except Exception as e:
        print(f"Error forgiving tasks for child {child_id}: {e}")
        flash('An error occurred while trying to forgive tasks.', 'error')

    # 5. Redirect back to the previous page
    return redirect(request.referrer or url_for('personal_dashboard'))
# --- END NEW ROUTE ---

################################################################################
# 13. MAIN EXECUTION
################################################################################
if __name__ == '__main__':
    try:
        # use_reloader=False is crucial for debug mode to prevent scheduler running twice
        app.run(debug=True, port=5001, use_reloader=False)
    finally:
        if scheduler.running:
            scheduler.shutdown()
            print("Scheduler shut down.")