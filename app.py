import os
import io
import json
import csv
import itertools
import qrcode
from datetime import datetime, timedelta, date, timezone
from collections import defaultdict
import pytz # Import timezone library

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
from pymongo import MongoClient, ASCENDING, DESCENDING
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
rewards_collection = db['rewards']
transactions_collection = db['transactions']
moods_collection = db['moods']
famjam_plans_collection = db['famjam_plans']
timers_collection = db['timers']

notes_collection = db['notes']
personal_todos_collection = db['personal_todos']
challenges_collection = db['challenges']
direct_messages_collection = db['direct_messages']

# NEW COLLECTION FOR MULTI-PARENT SUPPORT
families_collection = db['families']

################################################################################
# 3. RECOMMENDED INDEXES
################################################################################
users_collection.create_index([('email', ASCENDING)], unique=True, sparse=True)
# Index updated to ensure username uniqueness is constrained by the new family_id
users_collection.create_index([('username', ASCENDING), ('family_id', ASCENDING)], unique=True, sparse=True)
events_collection.create_index([('family_id', ASCENDING), ('due_date', ASCENDING)])

# *** FIX: Added unique compound index to prevent duplicate chores ***
# This index ensures that a chore with the same name cannot be assigned to the
# same person on the same day for the same family, preventing duplicates.
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

################################################################################
# 4. BCRYPT, LOGIN MANAGER, AND MODELS
################################################################################
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Moods configuration
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
        self.role = user_data['role']  # 'parent' or 'child'
        # family_id is now the unique ObjectId string of the dedicated Family document
        self.family_id = user_data.get('family_id')
        self.points = user_data.get('points', 0)
        self.lifetime_points = user_data.get('lifetime_points', 0)

    @staticmethod
    def get(user_id):
        try:
            data = users_collection.find_one({'_id': ObjectId(user_id)})
            if data:
                # Ensure the user's role is valid
                if data.get('role') not in ['parent', 'child']:
                    return None
                return User(data)
        except:
            return None
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

class MongoJsonEncoder(json.JSONEncoder):
    """Convert Mongo ObjectId/dates/etc. to JSON-serializable forms."""
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
        return redirect(url_for('family_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('family_dashboard'))

    if request.method == 'POST':
        identifier = request.form['email_or_username']
        user_data = users_collection.find_one({
            '$or': [{'email': identifier}, {'username': identifier}]
        })
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

@app.route('/terms')
def terms_of_service():
    """Renders the terms of service page."""
    return render_template('terms.html')

@app.route('/privacy')
def privacy_policy():
    """Renders the privacy policy page."""
    return render_template('privacy.html')

@app.route('/join/<invite_code>')
def join_family(invite_code):
    """General invite landing page (for child or second parent)."""
    try:
        family = families_collection.find_one({'_id': ObjectId(invite_code)})
        if not family:
            flash('This is not a valid invite code.', 'error')
            return redirect(url_for('login'))
    except:
        flash('Invalid invite code format.', 'error')
        return redirect(url_for('login'))

    # Get the username of the primary parent for a friendly message
    first_parent_id = family.get('parent_ids', [None])[0]
    parent = users_collection.find_one({'_id': first_parent_id})
    parent_name = parent.get('username', 'your family organizer') if parent else 'your family organizer'
    family_name = family.get('name', 'Family')

    # Pass the family_id instead of the parent_id
    return render_template(
        'index.html',
        page='join_family',
        parent_name=parent_name,
        family_name=family_name,
        invite_code=invite_code
    )

@app.route('/register/parent', methods=['GET', 'POST'])
def register_parent():
    """First parent registration (creates new family document)."""
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']

        if users_collection.find_one({'email': email}):
            flash('Email address already in use.', 'error')
            return redirect(url_for('register_parent'))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

        # 1. Create the Family Document FIRST
        family_doc = {
            'name': f"{username}'s Family",  # Or a better default name
            'parent_ids': [],
            'created_at': now_est(), # UPDATED to EST/EDT
        }
        family_id = families_collection.insert_one(family_doc).inserted_id
        family_id_str = str(family_id)

        # 2. Insert the Parent User
        new_id = users_collection.insert_one({
            'email': email,
            'username': username,
            'password_hash': hashed_pw,
            'role': 'parent',
            # New family_id points to the new family document's _id
            'family_id': family_id_str,
            'lifetime_points': 0,
            'points': 0
        }).inserted_id

        # 3. Update the Family Document with the new Parent's ID (as ObjectId)
        families_collection.update_one(
            {'_id': family_id},
            {'$push': {'parent_ids': new_id}}
        )

        flash('Parent account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('index.html', page='register_parent')

@app.route('/register/parent/<family_id>', methods=['GET', 'POST'])
def register_secondary_parent(family_id):
    """Allows a second parent to join an existing family."""
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

        # Check uniqueness globally for email, and within family for username
        if users_collection.find_one({'$or': [{'email': email}, {'username': username, 'family_id': family_id}]}):
            flash('Email or username already in use in this family.', 'error')
            return redirect(url_for('register_secondary_parent', family_id=family_id))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_parent_id = users_collection.insert_one({
            'email': email,
            'username': username,
            'password_hash': hashed_pw,
            'role': 'parent',
            'family_id': family_id,  # String OID of the family document
            'lifetime_points': 0,
            'points': 0
        }).inserted_id

        # Add the new parent's ID to the family's parent_ids list
        families_collection.update_one(
            {'_id': ObjectId(family_id)},
            {'$push': {'parent_ids': new_parent_id}}
        )

        flash(f'Welcome to {family.get("name", "the family")}! Please log in.', 'success')
        return redirect(url_for('login'))

    family_name = family.get('name', 'Family')
    return render_template('index.html', page='register_parent', family_id=family_id, family_name=family_name)

@app.route('/join')
@login_required
def invite():
    """Generates the invite links for children and other parents."""
    if current_user.role != 'parent':
        return redirect(url_for('family_dashboard'))

    # Use the current user's family_id as the invite code
    family_id_str = current_user.family_id

    # Two separate links for clarity on the invite page
    invite_url_child = f"{BASE_URL}{url_for('join_family', invite_code=family_id_str)}"
    invite_url_parent = f"{BASE_URL}{url_for('register_secondary_parent', family_id=family_id_str)}"

    # The QR code will point to the general join page
    qr_code_url = f"{BASE_URL}{url_for('join_family', invite_code=family_id_str)}"

    return render_template(
        'index.html',
        page='invite',
        invite_url_child=invite_url_child,
        invite_url_parent=invite_url_parent,
        qr_code_url=qr_code_url
    )

@app.route('/qr_code')
@login_required
def qr_code():
    """Serves the QR code image for the general family join link."""
    if current_user.role != 'parent':
        return Response(status=403)
    # The invite code is now the family_id
    invite_url = f"{BASE_URL}{url_for('join_family', invite_code=current_user.family_id)}"
    img = qrcode.make(invite_url, border=2)
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return Response(buf, mimetype='image/png')

@app.route('/register/child/<invite_code>', methods=['GET', 'POST'])
def register_child(invite_code):
    """Child registration, linked to the Family ID (invite_code)."""
    try:
        # Check if the invite_code is a valid Family ID
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

        # Check uniqueness within family (uses family_id string)
        if users_collection.find_one({'username': username, 'family_id': invite_code}):
            flash('Username already taken in this family.', 'error')
            return redirect(url_for('register_child', invite_code=invite_code))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        users_collection.insert_one({
            'username': username,
            'password_hash': hashed_pw,
            'role': 'child',
            'family_id': invite_code,  # Stored as Family ObjectId string
            'points': 0,
            'lifetime_points': 0
        })
        flash('Child account created! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('index.html', page='register_child', invite_code=invite_code)

################################################################################
# 6. CHILD PASSWORD RESET (PARENT ONLY)
################################################################################
@app.route('/child/reset-password/<child_id>', methods=['POST'])
@login_required
def reset_child_password(child_id):
    # 1. Authorization: Ensure the current user is a parent
    if current_user.role != 'parent':
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('personal_dashboard'))

    new_password = request.form.get('new_password')

    # 2. Validation
    if not new_password or len(new_password) < 6:
        flash('Please provide a new password that is at least 6 characters long.', 'error')
        return redirect(url_for('personal_dashboard'))  # Or back to the management modal

    # 3. Security Check (uses family_id string)
    child = users_collection.find_one({
        '_id': ObjectId(child_id),
        'family_id': current_user.family_id,
        'role': 'child'
    })
    if not child:
        flash('Child not found in your family.', 'error')
        return redirect(url_for('personal_dashboard'))

    # 4. Action
    hashed_pw = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users_collection.update_one(
        {'_id': ObjectId(child_id)},
        {'$set': {'password_hash': hashed_pw}}
    )
    flash(f"Password for {child.get('username')} has been successfully reset.", 'success')
    return redirect(url_for('personal_dashboard'))

################################################################################
# 7. DASHBOARD ROUTES
################################################################################
@app.route('/dashboard')
@login_required
def personal_dashboard():
    # Helper for all family artifact queries
    family_oid = ObjectId(current_user.family_id)
    today = today_est() # Today's date in EST/EDT
    
    # Fetch personal items for ANY logged in user (notes and todos use user_id)
    personal_notes = list(notes_collection.find({'user_id': ObjectId(current_user.id)}).sort('created_at', DESCENDING))
    personal_todos = list(personal_todos_collection.find({'user_id': ObjectId(current_user.id)}).sort('created_at', DESCENDING))

    # --- PARENT LOGIC ---
    if current_user.role == 'parent':
        # Parent's "Manage Tasks" dashboard
        family_members = list(users_collection.find({'family_id': current_user.family_id}))
        member_map = {str(m['_id']): m['username'] for m in family_members}
        for member in family_members:
            member['_id'] = str(member['_id'])

        # Fetch events for "Pending Approvals" list
        events = list(events_collection.find({
            'family_id': family_oid,
            'status': {'$in': ['completed', 'approved']}
        }).sort('due_date', DESCENDING).limit(20))

        # Reward Requests
        reward_requests_cursor = rewards_collection.find({
            'family_id': family_oid,
            'status': 'requested'
        }).sort('_id', -1)
        reward_requests = []
        for r in reward_requests_cursor:
            r['requested_by_username'] = member_map.get(str(r.get('requested_by_id')), 'Unknown')
            reward_requests.append(r)

        # Transaction History
        now = now_est()
        spend_tx = list(transactions_collection.find({
            'family_id': family_oid
        }).sort('spent_at', DESCENDING))
        for t in spend_tx:
            # Add a 'completed_at_pretty' field for display
            if t.get('spent_at'):
                delta = now - t['spent_at'].astimezone(TIMEZONE)
                if delta.days > 0:
                    t['spent_at_pretty'] = f"{delta.days}d ago"
                elif delta.seconds > 3600:
                    t['spent_at_pretty'] = f"{delta.seconds // 3600}h ago"
                else:
                    t['spent_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"
        
        # Add 'completed_at_pretty' for pending approval events
        for event in events:
            if event.get('completed_at'):
                delta = now - event['completed_at'].astimezone(TIMEZONE)
                if delta.days > 0:
                    event['completed_at_pretty'] = f"Completed {delta.days}d ago"
                elif delta.seconds > 3600:
                    event['completed_at_pretty'] = f"Completed {delta.seconds // 3600}h ago"
                else:
                    event['completed_at_pretty'] = f"Completed {max(1, delta.seconds // 60)}m ago"


        # Active FamJam Plan
        active_famjam_plan = famjam_plans_collection.find_one({
            'family_id': family_oid,
            'status': 'active'
        })
        if active_famjam_plan:
            today_dt = now_est()
            start_date = active_famjam_plan['start_date']
            end_date = active_famjam_plan['end_date']
            start_date_aware = start_of_day_est(start_date.date())
            end_date_aware = start_of_day_est(end_date.date())
            
            total_days = (end_date_aware - start_date_aware).days
            if total_days > 0:
                days_passed = (today_dt - start_date_aware).days
                active_famjam_plan['progress_percent'] = min(100, max(0, (days_passed / total_days) * 100))
            else:
                active_famjam_plan['progress_percent'] = 100
            active_famjam_plan['days_left'] = max(0, (end_date_aware - today_dt).days)

        # Challenges
        challenges = list(challenges_collection.find({'family_id': family_oid}))
        for c in challenges:
            c['claimer_username'] = member_map.get(str(c.get('claimed_by_id')), '')

        return render_template(
            'index.html',
            page='dashboard_parent',
            family_members=family_members,
            events=events,
            reward_requests=reward_requests,
            member_map=member_map,
            spend_history=spend_tx,
            active_famjam_plan=active_famjam_plan,
            personal_notes=personal_notes,
            personal_todos=personal_todos,
            challenges=challenges,
            today_date=today,
            now_est=now_est,
            TIMEZONE=TIMEZONE
        )
    # --- CHILD LOGIC (Corrected for 3-Tab View) ---
    else:
        # Child's "My Day" dashboard logic
        start_of_today = start_of_day_est(today)
        end_of_today = start_of_today + timedelta(days=1)
        # Define the 7-day boundary for the 'Upcoming' tab
        seven_days_from_now = start_of_today + timedelta(days=8)

        # 1. Fetch ALL relevant chores (overdue, today, and upcoming)
        #    This gets all chores that aren't fully approved yet for the template to filter.
        chores_cursor = events_collection.find({
            'assigned_to': current_user.id,
            'type': 'chore',
            'status': {'$in': ['assigned', 'completed']} 
        }).sort('due_date', ASCENDING)
        
        child_events = list(chores_cursor) # Start the list with all chores

        # 2. Fetch HABITS for today ONLY.
        habits_cursor = events_collection.find({
            'assigned_to': current_user.id,
            'type': 'habit',
            'due_date': {'$gte': start_of_today, '$lt': end_of_today},
        })

        for e in habits_cursor:
            # This logic determines if a habit can be checked in today
            last_check = e.get('last_completed')
            last_completed_date_est = last_check.astimezone(TIMEZONE).date() if last_check else None
            e['can_checkin'] = not (last_completed_date_est and last_completed_date_est == today)
            child_events.append(e) # Add the processed habit to the main list
        
        # --- The rest of the data fetching for the child dashboard ---
        now = now_est()
        child_rewards = list(rewards_collection.find({
            'requested_by_id': current_user.id
        }))
        for reward in child_rewards:
            if reward.get('status') in ['approved', 'rejected'] and reward.get('resolved_at'):
                resolved_at_aware = reward['resolved_at'].astimezone(TIMEZONE)
                delta = now - resolved_at_aware
                if delta.days > 0:
                    reward['resolved_at_pretty'] = f"{delta.days}d ago"
                elif delta.seconds > 3600:
                    reward['resolved_at_pretty'] = f"{delta.seconds // 3600}h ago"
                else:
                    minutes_ago = max(1, delta.seconds // 60)
                    reward['resolved_at_pretty'] = f"{minutes_ago}m ago"

        challenges = list(challenges_collection.find({
            'family_id': family_oid,
            'status': {'$in': ['open', 'in_progress', 'completed']}
        }).sort('created_at', DESCENDING))

        child_id = ObjectId(current_user.id)
        direct_messages_cursor = direct_messages_collection.find({
            'family_id': family_oid,
            '$or': [
                {'sender_id': child_id},
                {'recipient_id': child_id}
            ]
        }).sort('sent_at', ASCENDING)
        direct_messages = list(direct_messages_cursor)
        for msg in direct_messages:
            sent_at_aware = msg['sent_at'].astimezone(TIMEZONE)
            delta = now - sent_at_aware
            if delta.days > 1:
                msg['sent_at_pretty'] = sent_at_aware.strftime('%b %d')
            elif delta.days == 1:
                msg['sent_at_pretty'] = "Yesterday"
            elif delta.seconds > 3600:
                msg['sent_at_pretty'] = f"{delta.seconds // 3600}h ago"
            else:
                msg['sent_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"

        return render_template(
            'index.html',
            page='dashboard_child',
            events=child_events,
            rewards=child_rewards,
            personal_notes=personal_notes,
            personal_todos=personal_todos,
            challenges=challenges,
            direct_messages=direct_messages,
            today_date=today,
            TIMEZONE=TIMEZONE,
            seven_days_from_now=seven_days_from_now
        )



@app.route('/family-dashboard')
@login_required
def family_dashboard():
    fam_id = current_user.family_id
    fam_oid = ObjectId(fam_id)  # Helper for OID-based collections

    # Users collection uses string ID
    family_members = list(users_collection.find({'family_id': fam_id}))
    for member in family_members:
        member['_id'] = str(member['_id'])
    member_map = {str(m['_id']): m['username'] for m in family_members}

    # +++ FIX 1: Get a set of child IDs for efficient filtering +++
    # This creates a set of all user IDs that belong to children for quick lookups.
    child_ids = {str(m['_id']) for m in family_members if m.get('role') == 'child'}

    # Events collection uses OID
    events = list(events_collection.find({'family_id': fam_oid}))

    # Basic stats
    stats = {
        "completed_this_week": 0,
        "pending_approval": 0,
        # This calculation was already correct as it filters by role.
        "total_points_awarded": sum(
            m.get('lifetime_points', 0) for m in family_members if m.get('role') == 'child'
        ),
        "weekly_completion_data": {"labels": [], "data": []}
    }

    now = now_est() # Uses timezone-aware helper
    one_week_ago = now - timedelta(days=7)
    # Initialize counts for the last 7 days, including today
    day_counts = {(now.date() - timedelta(days=i)).strftime('%a'): 0 for i in range(7)}

    for e in events:
        assignee_id_str = str(e.get('assigned_to'))

        # +++ FIX 2: Skip any event that is not assigned to a child +++
        # If the event's assignee is not in our set of child IDs, we ignore it
        # and move to the next event in the loop. This is the key change.
        if assignee_id_str not in child_ids:
            continue

        # The rest of this logic now only processes tasks belonging to children.
        if e.get('status') == 'completed':
            stats['pending_approval'] += 1
        
        if e.get('status') == 'approved' and e.get('approved_at'):
            # Make approved_at timezone aware for comparison
            approved_at_aware = e['approved_at'].astimezone(TIMEZONE)
            if approved_at_aware > one_week_ago:
                stats['completed_this_week'] += 1
                day_label = approved_at_aware.strftime('%a')
                if day_label in day_counts:
                    day_counts[day_label] += 1

    stats['weekly_completion_data']['labels'] = list(day_counts.keys())[::-1]
    stats['weekly_completion_data']['data'] = list(day_counts.values())[::-1]

    # --- The rest of the function remains the same ---

    # Recent events (Events collection uses OID)
    rec_cursor = events_collection.find({
        'family_id': fam_oid,
        'status': 'approved',
        # +++ FIX 3: Also filter recent events to only show children's accomplishments +++
        'assigned_to': {'$in': list(child_ids)}
    }).sort('approved_at', DESCENDING).limit(5)
    
    recent_events = []
    for ev in rec_cursor:
        ev['assigned_to_username'] = member_map.get(str(ev.get('assigned_to')), 'Unknown')
        if ev.get('approved_at'):
            approved_at_aware = ev['approved_at'].astimezone(TIMEZONE)
            delta = now - approved_at_aware
            if delta.days > 0:
                ev['approved_at_pretty'] = f"{delta.days}d ago"
            elif delta.seconds > 3600:
                ev['approved_at_pretty'] = f"{delta.seconds // 3600}h ago"
            else:
                ev['approved_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"
        else:
            ev['approved_at_pretty'] = 'Recently'
        recent_events.append(ev)

    # Load family timers (Timers collection uses OID)
    timers_cursor = timers_collection.find({'family_id': fam_oid}).sort('end_date', ASCENDING)
    timers = []
    for t in timers_cursor:
        creator_name = member_map.get(str(t.get('created_by')), "Unknown")
        end_date_aware = start_of_day_est(t['end_date'].date())
        
        delta = end_date_aware - now
        if delta.total_seconds() < 0:
            time_left = "Timer ended"
        else:
            days_left = delta.days
            if days_left >= 1:
                time_left = f"{days_left} day{'s' if days_left != 1 else ''} left"
            else:
                hours = delta.seconds // 3600
                minutes = (delta.seconds % 3600) // 60
                if hours > 0:
                        time_left = f"{hours} hour{'s' if hours != 1 else ''} left"
                else:
                    time_left = f"{minutes} minute{'s' if minutes != 1 else ''} left"

        timers.append({
            'name': t['name'],
            'end_date': end_date_aware.strftime('%b %d, %Y'),
            'creator_name': creator_name,
            'time_left': time_left
        })

    # Load family challenges (Challenges collection uses OID)
    challenges_cursor = challenges_collection.find({'family_id': fam_oid}).sort('created_at', DESCENDING)
    challenges = []
    for c in challenges_cursor:
        c['creator_username'] = member_map.get(str(c.get('created_by_id')), 'Unknown')
        c['claimer_username'] = member_map.get(str(c.get('claimed_by_id')), '')
        challenges.append(c)

    return render_template(
        'index.html',
        page='family_dashboard',
        stats=stats,
        family_members=family_members,
        recent_events=recent_events,
        timers=timers,
        challenges=challenges
    )



@app.route('/calendar-focus')
@login_required
def calendar_focus():
    # Uses family_id string for users collection
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
# 8. TIMERS
################################################################################
@app.route('/timer/create', methods=['POST'])
@login_required
def create_timer():
    timer_name = request.form.get('name', '').strip()
    timer_date_str = request.form.get('end_date', '')

    if not timer_name or not timer_date_str:
        flash("Please provide a timer name and an end date.", "error")
        return redirect(url_for('family_dashboard'))

    try:
        # We assume the user enters a naive date, so we treat it as midnight EST/EDT
        end_date = start_of_day_est(datetime.strptime(timer_date_str, '%Y-%m-%d').date())
    except ValueError:
        flash("Invalid date format. Please use YYYY-MM-DD.", "error")
        return redirect(url_for('family_dashboard'))

    # Timers collection uses OID
    new_timer = {
        'name': timer_name,
        'end_date': end_date,
        'family_id': ObjectId(current_user.family_id),
        'created_by': ObjectId(current_user.id),
        'created_at': now_est() # UPDATED to EST/EDT
    }
    timers_collection.insert_one(new_timer)
    flash("Timer created successfully!", "success")
    return redirect(url_for('family_dashboard'))

################################################################################
# 9. CHALLENGES
################################################################################
@app.route('/challenge/create', methods=['POST'])
@login_required
def create_challenge():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    points_str = request.form.get('points', '0')

    if not title or not description:
        flash("Challenge title and description are required.", "error")
        return redirect(url_for('family_dashboard'))

    try:
        points = int(points_str)
        if points <= 0:
            raise ValueError()
    except ValueError:
        flash("Please enter a valid, positive number for points.", "error")
        return redirect(url_for('family_dashboard'))

    # Challenges collection uses OID
    challenge = {
        "family_id": ObjectId(current_user.family_id),
        "title": title,
        "description": description,
        "points": points,
        "status": "open",  # States: open, in_progress, completed, approved
        "created_by_id": ObjectId(current_user.id),
        "created_at": now_est(), # UPDATED to EST/EDT
        "claimed_by_id": None,
        "claimed_at": None,
        "completed_at": None,
        "approved_at": None
    }
    challenges_collection.insert_one(challenge)
    flash("New family challenge has been posted!", "success")
    return redirect(url_for('family_dashboard'))

@app.route('/challenge/claim/<challenge_id>')
@login_required
def claim_challenge(challenge_id):
    if current_user.role != 'child':
        flash("Only children can claim challenges.", "error")
        return redirect(url_for('family_dashboard'))

    # Challenges collection uses OID
    challenge = challenges_collection.find_one({
        '_id': ObjectId(challenge_id),
        'family_id': ObjectId(current_user.family_id)
    })
    if not challenge:
        flash("Challenge not found.", "error")
        return redirect(url_for('family_dashboard'))
    if challenge['status'] != 'open':
        flash("This challenge is no longer open to be claimed.", "error")
        return redirect(url_for('family_dashboard'))

    challenges_collection.update_one(
        {'_id': ObjectId(challenge_id)},
        {'$set': {
            'status': 'in_progress',
            'claimed_by_id': ObjectId(current_user.id),
            'claimed_at': now_est() # UPDATED to EST/EDT
        }}
    )
    flash(f"You have claimed the challenge '{challenge['title']}'! Good luck!", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/challenge/complete/<challenge_id>')
@login_required
def complete_challenge(challenge_id):
    # Challenges collection uses OID
    challenge = challenges_collection.find_one({
        '_id': ObjectId(challenge_id),
        'claimed_by_id': ObjectId(current_user.id),
        'status': 'in_progress'
    })
    if not challenge:
        flash("This challenge could not be marked as complete.", "error")
        return redirect(url_for('personal_dashboard'))

    challenges_collection.update_one(
        {'_id': ObjectId(challenge_id)},
        {'$set': {
            'status': 'completed',
            'completed_at': now_est() # UPDATED to EST/EDT
        }}
    )
    flash("Challenge marked as complete! Awaiting approval.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/challenge/approve/<challenge_id>')
@login_required
def approve_challenge(challenge_id):
    if current_user.role != 'parent':
        flash("Only parents can approve challenges.", "error")
        return redirect(url_for('personal_dashboard'))

    # Challenges collection uses OID
    challenge = challenges_collection.find_one({
        '_id': ObjectId(challenge_id),
        'family_id': ObjectId(current_user.family_id),
        'status': 'completed'
    })
    if not challenge:
        flash("This challenge is not ready for approval.", "error")
        return redirect(url_for('personal_dashboard'))

    # Award points
    users_collection.update_one(
        {'_id': challenge['claimed_by_id']},
        {'$inc': {'points': challenge['points'], 'lifetime_points': challenge['points']}}
    )
    challenges_collection.update_one(
        {'_id': ObjectId(challenge_id)},
        {'$set': {
            'status': 'approved',
            'approved_at': now_est() # UPDATED to EST/EDT
        }}
    )
    flash(f"Challenge approved! {challenge['points']} points awarded.", "success")
    return redirect(url_for('personal_dashboard'))

@app.route('/challenge/delete/<challenge_id>')
@login_required
def delete_challenge(challenge_id):
    # Allow parent to delete their own open challenges
    # Challenges collection uses OID
    challenge = challenges_collection.find_one({
        '_id': ObjectId(challenge_id),
        'family_id': ObjectId(current_user.family_id),
        'created_by_id': ObjectId(current_user.id),
        'status': 'open'
    })
    if not challenge:
        flash("You can only delete your own challenges that haven't been claimed.", "error")
        return redirect(url_for('family_dashboard'))

    challenges_collection.delete_one({'_id': ObjectId(challenge_id)})
    flash("Challenge successfully deleted.", "success")
    return redirect(url_for('family_dashboard'))

################################################################################
# 10. PERSONAL NOTES & TODOS
################################################################################
@app.route('/account/change-password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')

    # 1. Validation
    if not current_password or not new_password:
        flash('Both current and new passwords are required.', 'error')
        return redirect(url_for('personal_dashboard'))  # Or an account settings page

    if len(new_password) < 8:
        flash('Your new password must be at least 8 characters long.', 'error')
        return redirect(url_for('personal_dashboard'))

    # 2. Verification
    user_data = users_collection.find_one({'_id': ObjectId(current_user.id)})
    if not user_data or not bcrypt.check_password_hash(user_data['password_hash'], current_password):
        flash('Your current password was incorrect. Please try again.', 'error')
        return redirect(url_for('personal_dashboard'))

    # 3. Action
    hashed_pw = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users_collection.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$set': {'password_hash': hashed_pw}}
    )

    # 4. Security
    logout_user()
    flash('Your password has been changed successfully. Please log in again.', 'success')
    return redirect(url_for('login'))

@app.route('/note/create', methods=['POST'])
@login_required
def create_note():
    content = request.form.get('note_content', '').strip()
    if content:
        notes_collection.insert_one({
            'user_id': ObjectId(current_user.id),
            'content': content,
            'created_at': now_est() # UPDATED to EST/EDT
        })
        flash('Note added!', 'success')
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/note/delete/<note_id>')
@login_required
def delete_note(note_id):
    result = notes_collection.delete_one({
        '_id': ObjectId(note_id),
        'user_id': ObjectId(current_user.id)
    })
    if result.deleted_count:
        flash('Note deleted.', 'success')
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/todo/create', methods=['POST'])
@login_required
def create_todo():
    title = request.form.get('todo_title', '').strip()
    if title:
        personal_todos_collection.insert_one({
            'user_id': ObjectId(current_user.id),
            'title': title,
            'is_done': False,
            'created_at': now_est() # UPDATED to EST/EDT
        })
        flash('To-do item added!', 'success')
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/todo/delete/<todo_id>')
@login_required
def delete_todo(todo_id):
    result = personal_todos_collection.delete_one({
        '_id': ObjectId(todo_id),
        'user_id': ObjectId(current_user.id)
    })
    if result.deleted_count:
        flash('To-do item deleted.', 'success')
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/todo/toggle/<todo_id>')
@login_required
def toggle_todo(todo_id):
    todo = personal_todos_collection.find_one({
        '_id': ObjectId(todo_id),
        'user_id': ObjectId(current_user.id)
    })
    if todo:
        personal_todos_collection.update_one(
            {'_id': ObjectId(todo_id)},
            {'$set': {'is_done': not todo.get('is_done', False)}}
        )
    return redirect(request.referrer or url_for('personal_dashboard'))

###############################################################################
# UNIFIED MESSAGE ROUTE FOR BETTER CHAT FUNCTIONALITY BETWEEN PARENT & CHILD
###############################################################################
@app.route('/message/send', methods=['POST'])
@login_required
def send_message():
    """
    A unified route for sending messages in the family.

    - If the user is a child, messages can be sent to parents OR other children.
    - If the user is a parent, messages can be sent to any family member.
    """
    message_content = request.form.get('message_content', '').strip()
    recipient_id = request.form.get('recipient_id', '').strip()

    if not message_content:
        flash("You cannot send an empty message.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))

    if not recipient_id:
        flash("Please select a valid recipient.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))

    try:
        recipient_oid = ObjectId(recipient_id)
    except:
        flash("Invalid recipient ID format.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 1. Validate the recipient is in the same family (Parent/Child)
    recipient = users_collection.find_one({
        '_id': recipient_oid,
        'family_id': current_user.family_id
    })

    if not recipient:
        flash("Invalid recipient ID or user not in your family.", "error")
        return redirect(request.referrer or url_for('personal_dashboard'))

    # 2. Insert the message document
    message_doc = {
        "family_id": ObjectId(current_user.family_id),
        "sender_id": ObjectId(current_user.id),
        "sender_username": current_user.username,
        "recipient_id": recipient_oid,
        "recipient_username": recipient.get('username', 'Unknown'), # Add recipient username for context
        "message_content": message_content,
        "sent_at": now_est(), # UPDATED to EST/EDT
        "is_read": False
    }
    direct_messages_collection.insert_one(message_doc)

    flash(f"Your message to {recipient.get('username')} has been sent!", "success")

    # If this was a JSON (AJAX) request, return JSON directly
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"status": "success"})
    return redirect(request.referrer or url_for('personal_dashboard'))

@app.route('/api/messages')
@login_required
def get_direct_messages():
    current_user_id = ObjectId(current_user.id)
    # Find messages where the current user is either the sender OR the recipient
    messages_cursor = direct_messages_collection.find({
        'family_id': ObjectId(current_user.family_id),
        '$or': [
            {'sender_id': current_user_id},
            {'recipient_id': current_user_id}
        ]
    }).sort('sent_at', DESCENDING)
    serializable_messages = json.loads(json_util.dumps(messages_cursor))
    return jsonify(serializable_messages)

@app.route('/api/message/mark-read', methods=['POST'])
@login_required
def mark_messages_read():
    data = request.get_json()
    message_ids_str = data.get('message_ids')

    if not isinstance(message_ids_str, list):
        return jsonify({"error": "Invalid input format. 'message_ids' must be a list."}), 400

    message_ids_obj = [ObjectId(msg_id) for msg_id in message_ids_str]
    # Only update messages where the current user is the recipient.
    result = direct_messages_collection.update_many(
        {
            '_id': {'$in': message_ids_obj},
            'family_id': ObjectId(current_user.family_id),  # Security check
            'recipient_id': ObjectId(current_user.id)  # Must be the recipient
        },
        {'$set': {'is_read': True}}
    )
    return jsonify({"status": "success", "modified_count": result.modified_count})

################################################################################
# 11. CHILD MANAGEMENT ROUTES
################################################################################
@app.route('/child/edit/<child_id>', methods=['POST'])
@login_required
def edit_child(child_id):
    if current_user.role != 'parent':
        flash('You do not have permission to do this.', 'error')
        return redirect(url_for('family_dashboard'))

    # Security check uses family_id string
    child = users_collection.find_one({
        '_id': ObjectId(child_id),
        'family_id': current_user.family_id
    })
    if not child:
        flash('Child not found in your family.', 'error')
        return redirect(url_for('personal_dashboard'))

    update_data = {}
    new_username = request.form.get('username')
    new_password = request.form.get('password')

    # Update username (check uniqueness uses family_id string)
    if new_username and new_username != child.get('username'):
        # Check uniqueness
        if users_collection.find_one({
            'username': new_username,
            'family_id': current_user.family_id,
            '_id': {'$ne': ObjectId(child_id)}
        }):
            flash('That username is already taken in your family.', 'error')
            return redirect(url_for('personal_dashboard'))
        update_data['username'] = new_username

    # Update password
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

    # Security check uses family_id string
    child = users_collection.find_one({
        '_id': ObjectId(child_id),
        'family_id': current_user.family_id,
        'role': 'child'
    })
    if child:
        users_collection.delete_one({'_id': ObjectId(child_id)})
        # Delete related artifacts (events, rewards, transactions, moods) using child ID
        events_collection.delete_many({'assigned_to': child_id})
        rewards_collection.delete_many({'requested_by_id': str(child['_id'])})
        transactions_collection.delete_many({'child_id': str(child['_id'])})
        moods_collection.delete_many({'user_id': ObjectId(child_id)})

        flash(f"{child.get('username')} has been removed from the family.", 'success')
    else:
        flash('Could not find the specified child in your family.', 'error')

    return redirect(url_for('personal_dashboard'))

################################################################################
# 12. EVENT / TASK CREATION & MANAGEMENT
################################################################################
@app.route('/event/create', methods=['POST'])
@login_required
def create_event():
    if current_user.role != 'parent':
        flash("You are not authorized to create tasks.", "error")
        return redirect(url_for('personal_dashboard'))

    assigned_to_value = request.form['assigned_to']
    assignee_ids = []

    if assigned_to_value == "__ALL__":
        children = list(users_collection.find({
            'family_id': current_user.family_id,  # users collection uses string
            'role': 'child'
        }, {'_id': 1}))
        if not children:
            flash("There are no children in the family to assign tasks to.", "warning")
            return redirect(url_for('personal_dashboard'))
        assignee_ids = [str(c['_id']) for c in children]
    else:
        assignee_ids.append(assigned_to_value)

    recurrence = request.form['recurrence']
    
    # User input date (naive date object assumed)
    input_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
    # Convert naive date input into an EST/EDT midnight datetime object for storage consistency
    start_date = start_of_day_est(input_date) 
    
    task_type = request.form['type']

    # FamJam plan query uses OID
    active_plan = famjam_plans_collection.find_one({
        'family_id': ObjectId(current_user.family_id),
        'status': 'active'
    })

    family_oid = ObjectId(current_user.family_id)  # Helper for event inserts
    all_events_to_insert = []

    for user_id in assignee_ids:
        base_doc = {
            'name': request.form['name'],
            'description': request.form['description'],
            'points': int(request.form['points']),
            'type': task_type,
            'family_id': family_oid,
            'status': 'assigned',
            'created_at': now_est(), # UPDATED to EST/EDT
            'assigned_to': user_id,
            'recurrence_id': ObjectId()
        }
        if task_type == 'habit':
            base_doc['streak'] = 0
            base_doc['last_completed'] = None

        if recurrence == 'none':
            doc = base_doc.copy()
            doc['due_date'] = start_date
            del doc['recurrence_id']
            if active_plan and start_of_day_est(active_plan['start_date'].date()) <= start_date <= start_of_day_est(active_plan['end_date'].date()):
                doc['source_type'] = 'manual'
            all_events_to_insert.append(doc)
        else:
            # We want recurrence for the next 90 days, counting from the input date
            end_date = start_date + timedelta(days=90)
            current_date = start_date
            delta = {
                'daily': timedelta(days=1),
                'weekly': timedelta(weeks=1),
                'monthly': relativedelta(months=1)
            }.get(recurrence)

            if not delta:
                flash("Invalid recurrence type selected.", "error")
                return redirect(url_for('personal_dashboard'))

            while current_date < end_date:
                doc = base_doc.copy()
                doc['due_date'] = current_date
                
                # Compare awareness: active_plan dates are likely naive/UTC from DB, so make them EST/EDT midnight
                if active_plan and start_of_day_est(active_plan['start_date'].date()) <= current_date <= start_of_day_est(active_plan['end_date'].date()):
                    doc['source_type'] = 'manual'
                    
                all_events_to_insert.append(doc)
                current_date += delta

    if all_events_to_insert:
        events_collection.insert_many(all_events_to_insert)
        total_events_created = len(all_events_to_insert)
        flash(f"{total_events_created} task(s) scheduled successfully!", 'success')
    else:
        flash("No events were scheduled.", "warning")

    return redirect(url_for('personal_dashboard'))

@app.context_processor
def inject_global_vars():
    """Makes essential data available to all templates."""
    if not current_user.is_authenticated:
        return {}

    # --- UNIFIED LOGIC FOR ALL AUTHENTICATED USERS ---
    # Fetch all family members (needed for recipient lists, dashboards, etc.)
    family_members_cursor = users_collection.find(
        {'family_id': current_user.family_id}
    )
    family_members = []
    parent = {} # Used for the child's 'parent' variable if needed
    
    # We load the family document once to determine the primary parent ID
    family_doc = families_collection.find_one({'_id': ObjectId(current_user.family_id)})
    primary_parent_oid = family_doc['parent_ids'][0] if family_doc and family_doc.get('parent_ids') else None

    for member in family_members_cursor:
        # Ensure user IDs are strings for easy use in JavaScript
        member['_id'] = str(member['_id'])
        
        # If this member is the primary parent, save them for the child context
        if primary_parent_oid and member.get('_id') == str(primary_parent_oid):
            parent = member

        family_members.append(member)
        
    # *** FIX: Fetch personal notes and todos here to make them globally available ***
    personal_notes = list(notes_collection.find({'user_id': ObjectId(current_user.id)}).sort('created_at', DESCENDING))
    personal_todos = list(personal_todos_collection.find({'user_id': ObjectId(current_user.id)}).sort('created_at', DESCENDING))

    # Logic for unread message badge (efficiently check for current user as recipient)
    unread_messages_exist = direct_messages_collection.find_one({
        'recipient_id': ObjectId(current_user.id),
        'is_read': False
    }) is not None

    return {
        'family_members': family_members, # Used by parents (and now children for chat dropdown)
        'parent': parent, # Used by children to identify the primary parent
        'unread_messages_exist': unread_messages_exist,
        'personal_notes': personal_notes, # Now available in all templates
        'personal_todos': personal_todos  # Now available in all templates
    }
@app.route('/event/edit/<event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
    if current_user.role != 'parent':
        flash("You are not authorized to edit tasks.", "error")
        return redirect(url_for('personal_dashboard'))

    # Events collection query uses OID
    event = events_collection.find_one({
        '_id': ObjectId(event_id),
        'family_id': ObjectId(current_user.family_id)
    })
    if not event:
        flash("Task not found or you don't have permission to edit it.", "error")
        return redirect(url_for('manage_plan'))

    # Convert input date to EST/EDT midnight
    input_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
    due_date_aware = start_of_day_est(input_date)

    update_data = {
        'name': request.form['name'],
        'description': request.form['description'],
        'points': int(request.form['points']),
        'assigned_to': request.form['assigned_to'],
        'due_date': due_date_aware # UPDATED to EST/EDT
    }
    events_collection.update_one({'_id': ObjectId(event_id)}, {'$set': update_data})
    flash("Task has been updated successfully.", "success")
    return redirect(url_for('manage_plan'))

@app.route('/event/delete/<event_id>')
@login_required
def delete_event(event_id):
    if current_user.role != 'parent':
        flash("You are not authorized to delete tasks.", "error")
        return redirect(url_for('personal_dashboard'))

    # Events collection query uses OID
    result = events_collection.delete_one({
        '_id': ObjectId(event_id),
        'family_id': ObjectId(current_user.family_id)
    })
    if result.deleted_count > 0:
        flash("Task has been deleted successfully.", "success")
    else:
        flash("Task not found or you don't have permission to delete it.", "error")

    return redirect(request.referrer or url_for('manage_plan'))

@app.route('/event/complete/<event_id>')
@login_required
def complete_event(event_id):
    if current_user.role == 'child':
        # Mark chore as completed only if assigned to this child
        events_collection.update_one(
            {'_id': ObjectId(event_id), 'assigned_to': current_user.id, 'type': 'chore'},
            {'$set': {
                'status': 'completed',
                'completed_at': now_est() # UPDATED to EST/EDT
            }}
        )
        flash('Chore marked as complete! Awaiting approval.', 'success')

    return redirect(url_for('personal_dashboard'))

@app.route('/event/habit/checkin/<event_id>')
@login_required
def checkin_habit(event_id):
    if current_user.role == 'child':
        habit = events_collection.find_one({
            '_id': ObjectId(event_id),
            'assigned_to': current_user.id
        })
        if not habit:
            return redirect(url_for('personal_dashboard'))

        # Check against today's EST/EDT date
        today = today_est() 
        yesterday = today - timedelta(days=1)
        last_completed = habit.get('last_completed')
        curr_streak = habit.get('streak', 0)

        # Ensure last_completed is EST date for comparison
        last_completed_date_est = last_completed.astimezone(TIMEZONE).date() if last_completed else None

        if last_completed_date_est and last_completed_date_est == today:
            flash('You have already checked in for this habit today.', 'error')
            return redirect(url_for('personal_dashboard'))

        new_streak = curr_streak + 1 if (last_completed_date_est and last_completed_date_est == yesterday) else 1
        events_collection.update_one(
            {'_id': ObjectId(event_id)},
            {'$set': {
                'last_completed': now_est(), # UPDATED to EST/EDT
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
    if current_user.role == 'parent':
        e = events_collection.find_one_and_update(
            {'_id': ObjectId(event_id), 'family_id': ObjectId(current_user.family_id)},
            {'$set': {'status': 'approved', 'approved_at': now_est()}} # UPDATED to EST/EDT
        )
        if e and e.get('assigned_to'):
            users_collection.update_one(
                {'_id': ObjectId(e['assigned_to'])},
                {'$inc': {'points': e['points'], 'lifetime_points': e['points']}}
            )
            flash(f"Task approved! {e['points']} points awarded.", 'success')
    return redirect(url_for('personal_dashboard'))

################################################################################
# 13. REWARDS
################################################################################
@app.route('/reward/request', methods=['POST'])
@login_required
def request_reward():
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

        # Rewards collection insert uses OID
        reward_id = rewards_collection.insert_one({
            'name': request.form['name'],
            'points_cost': cost,
            'family_id': ObjectId(current_user.family_id),
            'requested_by_id': current_user.id,
            'status': 'requested',
            'resolved_at': None
        }).inserted_id

        # Transactions collection insert uses OID
        transactions_collection.insert_one({
            'reward_id': reward_id,
            'family_id': ObjectId(current_user.family_id),
            'child_id': current_user.id,
            'child_username': current_user.username,
            'reward_name': request.form['name'],
            'points_spent': cost,
            'status': 'pending',
            'spent_at': now_est(), # UPDATED to EST/EDT
            'resolved_at': None
        })
        flash('Reward requested! Points have been deducted; waiting on parent approval.', 'success')

    return redirect(url_for('personal_dashboard'))

@app.route('/reward/handle/<reward_id>/<action>')
@login_required
def handle_reward(reward_id, action):
    if current_user.role == 'parent':
        reward_obj_id = ObjectId(reward_id)

        reward = rewards_collection.find_one({
            '_id': reward_obj_id,
            'family_id': ObjectId(current_user.family_id)
        })
        if not reward:
            return redirect(url_for('personal_dashboard'))

        transaction_query = {
            'reward_id': reward_obj_id,
            'family_id': ObjectId(current_user.family_id)
        }

        if action == 'approve':
            rewards_collection.update_one(
                {'_id': reward_obj_id},
                {'$set': {'status': 'approved', 'resolved_at': now_est()}} # UPDATED to EST/EDT
            )
            transactions_collection.update_one(
                transaction_query,
                {'$set': {'status': 'approved', 'resolved_at': now_est()}} # UPDATED to EST/EDT
            )
            flash("Reward approved!", 'success')
        elif action == 'reject':
            # Refund child's points
            users_collection.update_one(
                {'_id': ObjectId(reward['requested_by_id'])},
                {'$inc': {'points': reward['points_cost']}}
            )
            rewards_collection.update_one(
                {'_id': reward_obj_id},
                {'$set': {'status': 'rejected', 'resolved_at': now_est()}} # UPDATED to EST/EDT
            )
            transactions_collection.update_one(
                transaction_query,
                {'$set': {'status': 'rejected', 'resolved_at': now_est()}} # UPDATED to EST/EDT
            )
            flash("Reward rejected. Points were refunded.", 'success')

    return redirect(url_for('personal_dashboard'))

################################################################################
# 14. API ROUTES (EVENTS & MOODS)
################################################################################
@app.route('/api/events')
@login_required
def api_events():
    fam_id = current_user.family_id
    fam_oid = ObjectId(fam_id)

    # --- (Your existing color mapping logic stays the same) ---
    child_colors = [
        '#ef4444', '#f97316', '#eab308', '#84cc16', '#22c55e',
        '#14b8a6', '#06b6d4', '#6366f1', '#a855f7', '#d946ef'
    ]
    default_color = '#6b7280'
    fam_members = list(users_collection.find({'family_id': fam_id}))
    member_map = {str(m['_id']): m['username'] for m in fam_members}
    child_color_map = {}
    children_in_family = [m for m in fam_members if m.get('role') == 'child']
    for i, child in enumerate(children_in_family):
        child_id_str = str(child['_id'])
        child_color_map[child_id_str] = child_colors[i % len(child_colors)]
    # --- (End of color logic) ---

    query = {'family_id': fam_oid}
    if (search := request.args.get('search')):
        query['name'] = regex.Regex(search, 'i')
    if (member_id := request.args.get('member')):
        query['assigned_to'] = member_id
    if (etype := request.args.get('type')):
        query['type'] = etype

    cursor = events_collection.find(query)
    calendar_events = []
    
    # 2. Get today's date once before the loop
    today = datetime.now(timezone.utc).date()

    for e in cursor:
        assigned_to_id = e.get('assigned_to')
        event_color = child_color_map.get(assigned_to_id, default_color)

        can_checkin = False
        if e.get('type') == 'habit':
            last_completed = e.get('last_completed')
            # Check if habit was already completed today (in EST/EDT)
            last_completed_date_est = last_completed.astimezone(TIMEZONE).date() if last_completed else None
            if not (last_completed_date_est and last_completed_date_est == today_est()):
                can_checkin = True
        calendar_events.append({
            'title': f"{e.get('type', 'Task').capitalize()}: {e['name']}",
            'start': e['due_date'].isoformat(),
            'allDay': True,
            'color': event_color,
            'extendedProps': {
                '_id': str(e['_id']),  # <-- ADD: Event's unique ID
                'type': e.get('type'),
                'description': e.get('description', 'No description.'),
                'points': e.get('points'),
                'status': e.get('status'),
                'assignee_name': member_map.get(assigned_to_id, 'N/A'),
                'assigned_to': assigned_to_id,
                'can_checkin': can_checkin # <-- ADD: The new flag
            }
        })

    return jsonify(calendar_events)

@app.route('/api/mood/log', methods=['POST'])
@login_required
def api_mood_log():
    data = request.json
    try:
        # We assume the user date input is in the local time (EST/EDT)
        input_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        entry_date_aware = start_of_day_est(input_date) # Store as EST midnight
        
        period = data['period']
        mood_emoji = data['emoji']
        note = data.get('note', '')
        mood_score = MOOD_EMOJI_TO_SCORE.get(mood_emoji)

        if not all([entry_date_aware, period, mood_emoji, mood_score is not None]):
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400

        moods_collection.update_one(
            {
                'user_id': ObjectId(current_user.id),
                'date': entry_date_aware, # Query/update using EST/EDT midnight date
                'period': period
            },
            {
                '$set': {
                    'mood_emoji': mood_emoji,
                    'mood_score': mood_score,
                    'note': note,
                    'updated_at': now_est() # UPDATED to EST/EDT
                },
                '$setOnInsert': {
                    'family_id': ObjectId(current_user.family_id),
                    'created_at': now_est() # UPDATED to EST/EDT
                }
            },
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
            # Query the date as EST midnight
            entry_date_naive = datetime.strptime(request.args['date'], '%Y-%m-%d').date()
            entry_date_aware = start_of_day_est(entry_date_naive)
            
            period = request.args['period']
            entry = moods_collection.find_one({
                'user_id': ObjectId(current_user.id),
                'date': entry_date_aware,
                'period': period
            })
            if entry:
                return jsonify(entry)
            else:
                return jsonify({'error': 'Not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    # Look back 30 days based on EST/EDT time
    thirty_days_ago = now_est() - timedelta(days=30)
    mood_entries = list(moods_collection.find({
        'user_id': ObjectId(current_user.id),
        'date': {'$gte': thirty_days_ago}
    }).sort('date', ASCENDING))

    labels = []
    data = []
    for e in mood_entries:
        # Convert stored date (which is EST midnight, stored as UTC) back to EST for display
        date_est = e['date'].astimezone(TIMEZONE) 
        labels.append(f"{date_est.strftime('%b %d')} {e['period']}")
        data.append(e['mood_score'])
        
    return jsonify({'labels': labels, 'data': data})

@app.route('/api/mood/family')
@login_required
def api_mood_family():
    # Look back 30 days based on EST/EDT time
    thirty_days_ago = now_est() - timedelta(days=30)
    
    pipeline_avg = [
        {
            '$match': {
                'family_id': ObjectId(current_user.family_id),
                'date': {'$gte': thirty_days_ago}
            }
        },
        {
            '$group': {
                '_id': '$date',
                'avgScore': {'$avg': '$mood_score'}
            }
        },
        {'$sort': {'_id': 1}}
    ]
    daily_avg_data = list(moods_collection.aggregate(pipeline_avg))
    
    # Process aggregation results to use EST for display
    daily_avg_labels = []
    for d in daily_avg_data:
        # Convert stored date (EST midnight) back to EST/EDT date for labeling
        date_est = d['_id'].astimezone(TIMEZONE)
        daily_avg_labels.append(date_est.strftime('%b %d'))

    pipeline_dist = [
        {
            '$match': {
                'family_id': ObjectId(current_user.family_id),
                'date': {'$gte': thirty_days_ago}
            }
        },
        {
            '$group': {
                '_id': '$mood_emoji',
                'count': {'$sum': 1}
            }
        },
        {'$sort': {'count': -1}}
    ]
    dist_data = list(moods_collection.aggregate(pipeline_dist))
    mood_map = {m['emoji']: m for m in MOOD_CONFIG['moods']}

    return jsonify({
        'daily_average': {
            'labels': daily_avg_labels,
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

################################################################################
# 15. FAMJAM PLAN MANAGEMENT
################################################################################
@app.route('/manage-plan')
@login_required
def manage_plan():
    if current_user.role != 'parent':
        flash("You don't have permission to view this page.", "error")
        return redirect(url_for('personal_dashboard'))

    family_oid = ObjectId(current_user.family_id)

    # FamJam plan query uses OID
    active_plan = famjam_plans_collection.find_one({
        'family_id': family_oid,
        'status': 'active'
    })
    if not active_plan:
        flash("There is no active FamJam plan to manage.", "error")
        return redirect(url_for('personal_dashboard'))

    sort_by = request.args.get('sort_by', 'due_date')
    order = request.args.get('order', 'asc')
    sort_order = ASCENDING if order == 'asc' else DESCENDING

    # Convert stored plan dates (naive/UTC) to EST midnight for boundary comparison
    start_date_aware = start_of_day_est(active_plan['start_date'].date())
    end_date_aware = start_of_day_est(active_plan['end_date'].date())

    query = {
        'family_id': family_oid,
        'due_date': {
            '$gte': start_date_aware,
            '$lte': end_date_aware
        }
    }
    tasks_cursor = events_collection.find(query).sort(sort_by, sort_order)

    # Users collection uses string
    family_members = list(users_collection.find({
        'family_id': current_user.family_id,
        'role': 'child'
    }))
    for member in family_members:
        member['_id'] = str(member['_id'])
    member_map = {str(m['_id']): m['username'] for m in family_members}

    tasks = []
    for task in tasks_cursor:
        task['assigned_to_username'] = member_map.get(str(task.get('assigned_to')), 'N/A')
        # Ensure task due_date is converted to EST for JSON serialization
        task['due_date_est'] = task['due_date'].astimezone(TIMEZONE)
        task['json_string'] = json.dumps(task, cls=MongoJsonEncoder)
        tasks.append(task)

    return render_template(
        'index.html',
        page='manage_plan',
        plan=active_plan,
        tasks=tasks,
        family_members=family_members,
        current_sort={'by': sort_by, 'order': order}
    )

@app.route('/plan/edit_name/<plan_id>', methods=['POST'])
@login_required
def edit_plan_name(plan_id):
    if current_user.role != 'parent':
        flash("You don't have permission to do this.", "error")
        return redirect(url_for('personal_dashboard'))

    new_name = request.form.get('plan_name')
    if not new_name or not new_name.strip():
        flash("Plan name cannot be empty.", "error")
        return redirect(url_for('manage_plan'))

    result = famjam_plans_collection.update_one(
        {
            '_id': ObjectId(plan_id),
            'family_id': ObjectId(current_user.family_id)
        },
        {
            '$set': {'plan_data.plan_name': new_name.strip()}
        }
    )
    if result.modified_count > 0:
        flash("Plan name updated successfully.", "success")

    return redirect(url_for('manage_plan'))

################################################################################
# 16. AI & FAMJAM API HELPERS
################################################################################
@app.route('/api/famjam/suggest', methods=['POST'])
@login_required
def suggest_famjam_plan():
    """
    Calls OpenAI to generate a FamJam chore plan in a specific JSON format.
    """
    if current_user.role != 'parent':
        return jsonify({"error": "Only parents can generate FamJam plans."}), 403

    data = request.get_json() or {}
    goal = data.get('goal', 'general family teamwork and responsibility, promoting cleanliness and basic life skills')

    # Users collection query uses string
    children = list(users_collection.find({
        'family_id': current_user.family_id,
        'role': 'child'
    }, {'username': 1, '_id': 0}))

    if not children:
        return jsonify({"error": "You need at least one child in the family to create a plan."}), 400

    child_names = [c['username'] for c in children]

    system_prompt = f"""
             You are an expert family chore planner and motivator. Your task is to generate a JSON object
             representing a FamJam chore plan for a family with the following children: {', '.join(child_names)}.
             The plan's primary focus is: "{goal}".

             The plan MUST be returned as a single JSON object that strictly follows this structure:
             {{
               "plan_name": "[A creative and encouraging name for the plan]",
               "suggested_chores": [
                 {{
                   "name": "[Short chore name, e.g., 'Load Dishwasher']",
                   "description": "[A brief, specific description of the task]",
                   "points": [Points value, MUST be an integer between 10 and 50],
                   "type": "chore",
                   "recurrence": "[MUST be one of: 'daily', 'weekly', 'monthly']"
                 }}
               ]
             }}

             Generate 5 to 7 high-quality, relevant chore suggestions.
             Do not include any text outside of the JSON object.
    """

    try:
        if not openai_client:
            raise Exception("OPENAI_API_KEY is not configured on the server.")

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the FamJam chore plan now."}
            ]
        )
        try:
            plan_json = json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            print(f"AI response error: {response.choices[0].message.content}")
            return jsonify({"error": "AI returned an invalid JSON response."}), 500
    except Exception as e:
        error_message = f"Failed to generate plan: {str(e)}"
        print(error_message)
        return jsonify({"error": error_message}), 500

    today = now_est() # UPDATED to EST/EDT now
    
    # Logic to set quarterly start/end dates based on EST/EDT time
    quarter = (today.month - 1) // 3 + 1
    start_month = (quarter - 1) * 3 + 1
    
    # Calculate naive start/end dates for the quarter
    naive_start_date = today.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    naive_end_date = naive_start_date + relativedelta(months=3) - timedelta(days=1)
    
    # Convert naive dates to EST/EDT midnight timezone-aware datetimes for storage
    start_date_aware = start_of_day_est(naive_start_date.date())
    end_date_aware = start_of_day_est(naive_end_date.date())


    plan_document_id = famjam_plans_collection.insert_one({
        'plan_data': plan_json,
        'goal': goal,
        'family_id': ObjectId(current_user.family_id),
        'status': 'draft',
        'start_date': start_date_aware, # Stored as EST/EDT midnight
        'end_date': end_date_aware,     # Stored as EST/EDT midnight
        'created_at': now_est() # UPDATED to EST/EDT
    }).inserted_id

    plan_json['plan_id'] = str(plan_document_id)
    plan_json['start_date_str'] = start_date_aware.strftime('%B %d, %Y')
    plan_json['end_date_str'] = end_date_aware.strftime('%B %d, %Y')
    plan_json['family_children'] = children

    return jsonify(plan_json)

@app.route('/api/famjam/apply', methods=['POST'])
@login_required
def apply_famjam_plan():
    if current_user.role != 'parent':
        return jsonify({"error": "Only parents can apply FamJam plans."}), 403

    plan_data = request.json
    plan_id_str = plan_data.get('plan_id')
    if not plan_data or 'suggested_chores' not in plan_data or not plan_id_str:
        return jsonify({'error': 'Invalid plan format received.'}), 400

    family_oid = ObjectId(current_user.family_id)

    # Archive previous active plans
    famjam_plans_collection.update_many(
        {'family_id': family_oid, 'status': 'active'},
        {'$set': {'status': 'archived'}}
    )

    plan_data_to_save = {
        'plan_name': plan_data.get('plan_name'),
        'suggested_chores': plan_data.get('suggested_chores', [])
    }

    # Update new plan status to active
    famjam_plans_collection.update_one(
        {
            '_id': ObjectId(plan_id_str),
            'family_id': family_oid
        },
        {
            '$set': {
                'status': 'active',
                'applied_at': now_est(), # UPDATED to EST/EDT
                'plan_data': plan_data_to_save
            }
        }
    )

    children = list(users_collection.find({
        'family_id': current_user.family_id,
        'role': 'child'
    }, {'_id': 1}))
    if not children:
        return jsonify({"error": "No children found in the family to assign chores to."}), 400

    child_ids = [str(c['_id']) for c in children]
    child_cycler = itertools.cycle(child_ids)

    # Start date/time for chore generation: Midnight EST/EDT of today
    today_date_est = today_est()
    current_due_date = start_of_day_est(today_date_est)
    end_date = current_due_date + timedelta(days=90)


    # Delete existing auto-generated events for the family from today forward
    events_collection.delete_many({
        'family_id': family_oid,
        'source': 'FamJamPlan',
        'source_type': 'generated',
        'status': 'assigned',
        'due_date': {'$gte': current_due_date}
    })

    new_events = []
    for chore_template in plan_data.get('suggested_chores', []):
        recurrence = chore_template.get('recurrence', '').lower()
        if recurrence == 'daily':
            delta = timedelta(days=1)
        elif recurrence == 'weekly':
            delta = timedelta(weeks=1)
        elif recurrence == 'monthly':
            delta = relativedelta(months=1)
        else:
            continue

        assigned_to_value = chore_template.get('assigned_to')
        
        # Reset generation loop start point for each chore template
        loop_date = current_due_date

        while loop_date < end_date:
            # Determine who gets this specific instance of the chore
            assignees_for_this_instance = []
            if assigned_to_value == "__ALL__":
                assignees_for_this_instance = child_ids
            elif assigned_to_value in child_ids:
                assignees_for_this_instance = [assigned_to_value]
            else:
                # Fallback to cycling if not specified or invalid
                assignees_for_this_instance = [next(child_cycler)]

            # *** FIX: Removed the inefficient find_one() check from this loop ***
            for assigned_child_id in assignees_for_this_instance:
                doc = {
                    'name': chore_template.get('name'),
                    'description': chore_template.get('description'),
                    'points': int(chore_template.get('points', 0)),
                    'type': 'chore',
                    'family_id': family_oid,
                    'status': 'assigned',
                    'created_at': now_est(), # UPDATED to EST/EDT
                    'assigned_to': assigned_child_id,
                    'due_date': loop_date,
                    'source': 'FamJamPlan',
                    'source_type': 'generated'
                }
                new_events.append(doc)

            if isinstance(delta, relativedelta):
                loop_date += delta
            else:
                loop_date += delta

    if not new_events:
        return jsonify({
            'status': 'warning',
            'message': 'No new chores were scheduled. They may already exist for these dates.'
        })

    # *** FIX: Modified the insert_many call to handle duplicates gracefully ***
    try:
        # Use ordered=False to insert all valid documents and ignore duplicates
        events_collection.insert_many(new_events, ordered=False)
        return jsonify({
            'status': 'success',
            'message': f'{len(new_events)} chores have been scheduled for the next 90 days!'
        })
    except Exception as e:
        # Handle the expected error when duplicates are found. This is now a
        # success case, as it means the duplicates were correctly prevented.
        if "E11000 duplicate key error" in str(e):
             return jsonify({
                 'status': 'success',
                 'message': 'Chore plan applied successfully. Existing chores were not duplicated.'
               })
        # Handle other potential database errors
        return jsonify({'error': f'Failed to save the plan to the database: {e}'}), 500


@app.route('/api/suggest-username', methods=['POST'])
def suggest_username():
    data = request.get_json() or {}
    name = data.get('name', '')

    potential_suggestions = [
        "SparklingSky", "CoolPenguin", "MightyLion", "RadRocket", "ChillGamer",
        "NightOwl", "DazzlingSun", "GreenMystic", "HappyPanda", "LaughingLlama"
    ]
    unique_suggestions = []
    for username in potential_suggestions:
        if not users_collection.find_one({'username': regex.Regex(f'^{username}$', 'i')}):
            unique_suggestions.append(username)
        if len(unique_suggestions) >= 3:
            break

    return jsonify({'suggestions': unique_suggestions})

@app.route('/api/consult-ai', methods=['POST'])
@login_required
def consult_ai():
    if not openai_client:
        return jsonify({"error": "AI feature is not configured on the server."}), 503

    # Use EST/EDT time
    thirty_days_ago = now_est() - timedelta(days=30)
    mood_entries = list(moods_collection.find({
        'user_id': ObjectId(current_user.id),
        'date': {'$gte': thirty_days_ago}
    }).sort('date', ASCENDING))

    if len(mood_entries) < 5:
        return jsonify({
            "ai_response": (
                "### Not Enough Data\n\nPlease log at least 5 moods over a few different days "
                "for a meaningful analysis. The more you log, the better I can help you find patterns!"
            )
        }), 200

    mood_log_str = ""
    for entry in mood_entries:
        mood_desc = next((m['desc'] for m in MOOD_CONFIG['moods'] if m['score'] == entry['mood_score']), 'Unknown')
        # Format date using EST/EDT time
        date_est = entry['date'].astimezone(TIMEZONE).strftime('%Y-%m-%d')
        mood_log_str += f"- On {date_est} ({entry['period']}), I felt: {mood_desc}. Note: '{entry.get('note', 'N/A')}'\n"

    system_prompt = f"""
 User is a {current_user.role}. You are a supportive and insightful AI assistant named 'FAMJAM Insights'. Your purpose is to analyze a user's mood log and provide gentle, encouraging, and constructive feedback. You are NOT a medical professional, and you MUST start your response with a clear disclaimer: "**Disclaimer:** I am an AI assistant and not a medical professional. This is not medical advice. If you are struggling, please consult a healthcare provider."

 After the disclaimer, analyze the provided mood data. Your analysis should be in Markdown format and include:
 1. **Overall Summary:** A brief, positive summary of the user's emotional state over the period.
 2. **Potential Patterns:** Gently point out any recurring patterns.
 3. **Actionable Suggestions:** Offer 2-3 simple, positive, and actionable suggestions.
 4. **Encouraging Closing:** End with a warm and encouraging message.

 Keep the tone positive, empathetic, and non-judgemental. Do not be alarming. Focus on empowerment and self-awareness.
    """
    user_prompt = f"Here is my mood log for the past 30 days. Please analyze it for me:\n\n{mood_log_str}"

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
        )
        ai_response = response.choices[0].message.content
        return jsonify({"ai_response": ai_response})
    except Exception as e:
        error_message = f"An error occurred while consulting the AI: {str(e)}"
        print(error_message)
        return jsonify({"error": "Sorry, I was unable to connect to the AI service right now. Please try again later."}), 500

################################################################################
# 17. MAIN ENTRY POINT
################################################################################

################################################################################
# 18. FATHER-ADDS-ANOTHER-PARENT
################################################################################
@app.route('/parent/create_child', methods=['GET', 'POST'])
@login_required
def create_child_direct():
    """
    Allows a parent to create a new child account directly,
    bypassing the need for an invitation link.
    """
    # 1. Authorization: Ensure the user is a parent
    if current_user.role != 'parent':
        flash("Only parents can create child accounts directly.", 'error')
        return redirect(url_for('family_dashboard'))

    # 2. Handle the form submission
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        # 3. Validation
        if not username or not password:
            flash('Username and password are required fields.', 'error')
            return redirect(request.url)

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return redirect(request.url)

        # 4. Check for username uniqueness within the family
        if users_collection.find_one({
            'username': username,
            'family_id': current_user.family_id # users collection uses string family_id
        }):
            flash(f"The username '{username}' is already taken in your family.", 'error')
            return redirect(request.url)

        # 5. Create the new child user
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        users_collection.insert_one({
            'username': username,
            'password_hash': hashed_pw,
            'role': 'child',
            'family_id': current_user.family_id, # Assign to the parent's family
            'points': 0,
            'lifetime_points': 0
        })

        flash(f"Child account for '{username}' has been successfully created!", 'success')
        # Redirect to the dashboard where the parent can see the new child
        return redirect(url_for('personal_dashboard'))

    # 6. For a GET request, render the creation form
    # This assumes you have a template partial named 'create_child_direct.html'
    return render_template('index.html', page='create_child_direct')
@app.route('/parent/create_another_parent', methods=['GET', 'POST'])
@login_required
def create_another_parent():
    """
    A new route that allows ONLY the first parent in `parent_ids` to create
    an additional parent account on someone else's behalf, thus not requiring
    them to self-register with an invite link.
    """
    # Must be a parent
    if current_user.role != 'parent':
        flash("Only parents can create another parent's account.", 'error')
        return redirect(url_for('family_dashboard'))

    # Check if current_user is the *first* parent in `parent_ids`
    family = families_collection.find_one({'_id': ObjectId(current_user.family_id)})
    if not family or not family.get('parent_ids'):
        flash("Cannot locate your family record.", 'error')
        return redirect(url_for('family_dashboard'))

    # The 'father' is recognized as the first parent ID
    first_parent_id = family['parent_ids'][0]
    if first_parent_id != ObjectId(current_user.id):
        flash("Only the first (primary) parent may add another parent.", 'error')
        return redirect(url_for('family_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        # Basic validations
        if not email or not username or not password:
            flash('All fields are required: email, username, and password.', 'error')
            return redirect(request.url)

        # Check uniqueness in the family
        if users_collection.find_one({
            '$or': [
                {'email': email},
                {
                    'username': username,
                    'family_id': current_user.family_id
                }
            ]
        }):
            flash('That email or username is already in use in this family.', 'error')
            return redirect(request.url)

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

        # Insert new parent user
        new_parent_id = users_collection.insert_one({
            'email': email,
            'username': username,
            'password_hash': hashed_pw,
            'role': 'parent',
            'family_id': current_user.family_id,  # same str as father
            'lifetime_points': 0,
            'points': 0
        }).inserted_id

        # Append new parent's ID to the family's parent_ids
        families_collection.update_one(
            {'_id': ObjectId(current_user.family_id)},
            {'$push': {'parent_ids': new_parent_id}}
        )

        flash(f"Parent account for '{username}' created successfully!", 'success')
        return redirect(url_for('family_dashboard'))

    # If GET, render a generic form within your main template
    return render_template('index.html', page='create_another_parent')
if __name__ == '__main__':
    app.run(debug=True, port=5001)
