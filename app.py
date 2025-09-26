import os
import io
import json
import csv
from datetime import datetime, timedelta, date
import itertools

from flask import (
    Flask, render_template, request, redirect, url_for, flash, Response, jsonify
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

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a-super-secret-key-that-you-should-change')

# --- OpenAI setup ---
openai_client = OpenAI()

# --- Mongo setup ---
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
BASE_URL = os.environ.get('BASE_URL', 'https://famjam.oblivio-company.com')
client = MongoClient(MONGO_URI)
db = client['mchores_app']

users_collection = db['users']
events_collection = db['events']
rewards_collection = db['rewards']
transactions_collection = db['transactions']
moods_collection = db['moods']
famjam_plans_collection = db['famjam_plans']  # Stores FamJam plans

# Recommended indexes
users_collection.create_index([('email', ASCENDING)], unique=True, sparse=True)
users_collection.create_index([('username', ASCENDING), ('family_id', ASCENDING)], unique=True, sparse=True)
events_collection.create_index([('family_id', ASCENDING), ('due_date', ASCENDING)])
moods_collection.create_index([('user_id', ASCENDING), ('date', ASCENDING), ('period', ASCENDING)], unique=True)
moods_collection.create_index([('family_id', ASCENDING), ('date', ASCENDING)])
famjam_plans_collection.create_index([('family_id', ASCENDING), ('status', ASCENDING)])


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
    def default(self, obj):
        if isinstance(obj, (ObjectId, datetime, date)):
            return str(obj)
        return json_util.default(obj)

app.json_encoder = MongoJsonEncoder

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

        users_collection.update_one({'_id': new_id}, {'$set': {'family_id': str(new_id)}})

        flash('Parent account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('index.html', page='register_parent')

@app.route('/register/child/<invite_code>', methods=['GET', 'POST'])
def register_child(invite_code):
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
    if current_user.role != 'parent':
        return redirect(url_for('family_dashboard'))
    # Construct the full, shareable "magic link"
    invite_url = f"{BASE_URL}{url_for('join_family', invite_code=current_user.id)}"
    return render_template('index.html', page='invite', invite_url=invite_url)

@app.route('/qr_code')
@login_required
def qr_code():
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
    if current_user.role == 'parent':
        family_members = list(users_collection.find({'family_id': current_user.family_id}))
        member_map = {str(m['_id']): m['username'] for m in family_members}
        for member in family_members:
                member['_id'] = str(member['_id'])
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

        active_famjam_plan = famjam_plans_collection.find_one({
            'family_id': current_user.family_id,
            'status': 'active'
        })
        if active_famjam_plan:
            today = datetime.utcnow()
            start_date = active_famjam_plan['start_date']
            end_date = active_famjam_plan['end_date']
            total_days = (end_date - start_date).days
            if total_days > 0:
                days_passed = (today - start_date).days
                active_famjam_plan['progress_percent'] = min(100, max(0, (days_passed / total_days) * 100))
            else:
                active_famjam_plan['progress_percent'] = 100

            active_famjam_plan['days_left'] = max(0, (end_date - today).days)

        return render_template(
            'index.html',
            page='dashboard_parent',
            family_members=family_members,
            events=events,
            reward_requests=reward_requests,
            member_map=member_map,
            spend_history=spend_tx,
            active_famjam_plan=active_famjam_plan
        )

    else: # Child dashboard
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

@app.route('/manage-plan')
@login_required
def manage_plan():
    if current_user.role != 'parent':
        flash("You don't have permission to view this page.", "error")
        return redirect(url_for('personal_dashboard'))

    active_plan = famjam_plans_collection.find_one({
        'family_id': current_user.family_id,
        'status': 'active'
    })

    if not active_plan:
        flash("There is no active FamJam plan to manage.", "error")
        return redirect(url_for('personal_dashboard'))

    # Sorting logic
    sort_by = request.args.get('sort_by', 'due_date')
    order = request.args.get('order', 'asc')
    sort_order = ASCENDING if order == 'asc' else DESCENDING

    query = {
        'family_id': current_user.family_id,
        #allow manage all # 'source': 'FamJamPlan',
        'due_date': {'$gte': active_plan['start_date'], '$lte': active_plan['end_date']}
    }
    
    tasks_cursor = events_collection.find(query).sort(sort_by, sort_order)
    
    family_members = list(users_collection.find({'family_id': current_user.family_id, 'role': 'child'}))
    for member in family_members:
            member['_id'] = str(member['_id'])
    member_map = {str(m['_id']): m['username'] for m in family_members}
    
    tasks = []
    for task in tasks_cursor:
        task['assigned_to_username'] = member_map.get(str(task.get('assigned_to')), 'N/A')
        # Serialize task for JS modal
        task['json_string'] = json.dumps(task, cls=MongoJsonEncoder)
        tasks.append(task)
        
    return render_template(
        'index.html',
        page='manage_plan',
        plan=active_plan,
        tasks=tasks,
        family_members=family_members, # For the edit modal dropdown
        current_sort={'by': sort_by, 'order': order}
    )

# --- NEW ROUTE TO HANDLE EDITING THE PLAN NAME ---
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
        {'_id': ObjectId(plan_id), 'family_id': current_user.family_id},
        {'$set': {'plan_data.plan_name': new_name.strip()}}
    )

    if result.modified_count > 0:
        flash("Plan name updated successfully.", "success")
    
    return redirect(url_for('manage_plan'))

@app.route('/family-dashboard')
@login_required
def family_dashboard():
    fam_id = current_user.family_id
    family_members = list(users_collection.find({'family_id': fam_id}))
    for member in family_members:
        member['_id'] = str(member['_id'])
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

@app.route('/event/create', methods=['POST'])
@login_required
def create_event():
    # Ensure only parents can create tasks
    if current_user.role != 'parent':
        flash("You are not authorized to create tasks.", "error")
        return redirect(url_for('personal_dashboard'))

    # --- 1. Get all data from the form ---
    recurrence = request.form['recurrence']
    start_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d')
    task_type = request.form['type']
    
    # --- 2. Check for an active plan to correctly label manually added tasks ---
    active_plan = famjam_plans_collection.find_one({
        'family_id': current_user.family_id,
        'status': 'active'
    })
    
    # --- 3. Create a base document with all common task properties ---
    base_doc = {
        'name': request.form['name'],
        'description': request.form['description'],
        'points': int(request.form['points']),
        'type': task_type,
        'family_id': current_user.family_id,
        'status': 'assigned',
        'created_at': datetime.utcnow(),
        'assigned_to': request.form['assigned_to'],
        'recurrence_id': ObjectId() # A unique ID to group recurring tasks
    }
    
    # Add special fields if the task is a 'habit'
    if task_type == 'habit':
        base_doc['streak'] = 0
        base_doc['last_completed'] = None

    # --- 4. Handle a single, non-recurring task ---
    if recurrence == 'none':
        doc = base_doc.copy()
        doc['due_date'] = start_date
        del doc['recurrence_id'] # Not needed for a single task
        
        # If the task's due date falls within the active plan, label it as 'manual'
        if active_plan and active_plan['start_date'] <= doc['due_date'] <= active_plan['end_date']:
            doc['source_type'] = 'manual' 

        events_collection.insert_one(doc)
        flash(f"{task_type.capitalize()} created successfully!", 'success')
        
    # --- 5. Handle recurring tasks ---
    else:
        events_to_insert = []
        # Schedule recurring tasks for the next 90 days from the start date
        end_date = start_date + timedelta(days=90) 
        current_date = start_date

        # Determine the time interval based on the selected recurrence
        delta = {
            'daily': timedelta(days=1), 
            'weekly': timedelta(weeks=1), 
            'monthly': relativedelta(months=1)
        }.get(recurrence)
        
        if not delta:
            flash("Invalid recurrence type selected.", "error")
            return redirect(url_for('personal_dashboard'))

        # Loop from the start date until the end date, creating tasks at each interval
        while current_date <= end_date:
            doc = base_doc.copy()
            doc['due_date'] = current_date
            
            # If the instance's due date falls within the active plan, label it as 'manual'
            if active_plan and active_plan['start_date'] <= doc['due_date'] <= active_plan['end_date']:
                doc['source_type'] = 'manual'

            events_to_insert.append(doc)
            current_date += delta
        
        # Insert all generated events into the database in one operation
        if events_to_insert:
            events_collection.insert_many(events_to_insert)
            flash(f"Recurring {task_type} has been scheduled for the next 90 days!", 'success')
        else:
            flash("No events were scheduled.", "warning")

    return redirect(url_for('personal_dashboard'))
    
@app.route('/event/edit/<event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
    if current_user.role != 'parent':
        flash("You are not authorized to edit tasks.", "error")
        return redirect(url_for('personal_dashboard'))

    event = events_collection.find_one({'_id': ObjectId(event_id), 'family_id': current_user.family_id})
    if not event:
        flash("Task not found or you don't have permission to edit it.", "error")
        return redirect(url_for('manage_plan'))

    update_data = {
        'name': request.form['name'],
        'description': request.form['description'],
        'points': int(request.form['points']),
        'assigned_to': request.form['assigned_to'],
        'due_date': datetime.strptime(request.form['due_date'], '%Y-%m-%d')
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

    result = events_collection.delete_one({'_id': ObjectId(event_id), 'family_id': current_user.family_id})

    if result.deleted_count > 0:
        flash("Task has been deleted successfully.", "success")
    else:
        flash("Task not found or you don't have permission to delete it.", "error")
    
    return redirect(url_for('manage_plan'))

@app.route('/event/complete/<event_id>')
@login_required
def complete_event(event_id):
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

@app.route('/api/events')
@login_required
def api_events():
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

    system_prompt = "You are a supportive mental wellness assistant. Analyze the user's mood data and provide insights based on Cognitive Behavioral Therapy (CBT) principles. Format your response using markdown."
    user_prompt = (
        f"Here is my mood data in CSV format:\n{csv_content}\n\n"
        "Please provide a brief, supportive analysis of my mood patterns. "
        "Identify any potential patterns or triggers. Use markdown for readability, and bold key phrases with double asterisks."
    )

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        ai_response = completion.choices[0].message.content
        return jsonify({'ai_response': ai_response})
    except Exception as e:
        return jsonify({'error': f"Failed to connect to AI service: {e}"}), 503

@app.route('/api/famjam/suggest', methods=['POST'])
@login_required
def suggest_famjam_plan():
    if current_user.role != 'parent':
        return jsonify({"error": "Only parents can generate FamJam plans."}), 403

    data = request.get_json() or {}
    goal = data.get('goal', 'general family teamwork and responsibility')

    children = list(users_collection.find(
        {'family_id': current_user.family_id, 'role': 'child'},
        {'username': 1, '_id': 0}
    ))
    if not children:
        return jsonify({"error": "You need at least one child in the family to create a plan."}), 400

    child_usernames = [c['username'] for c in children]
    past_chores = list(events_collection.find(
        {'family_id': current_user.family_id, 'status': 'approved', 'type': {'$in': ['chore', 'habit']}},
        {'name': 1, 'points': 1, 'type': 1, '_id': 0}
    ).limit(30))

    system_prompt = "You are a helpful assistant designed to create balanced, quarterly chore plans (FamJam Plans) for families. Your response must be a valid JSON object."
    today = datetime.utcnow()

    quarter = (today.month - 1) // 3 + 1
    start_month = (quarter - 1) * 3 + 1
    
    start_date = today.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date + relativedelta(months=3) - timedelta(days=1)
    
    default_plan_name = f"Family FamJam - Q{quarter} {today.year}"

    user_prompt = (
        f"Family context: This family has {len(child_usernames)} children named {', '.join(child_usernames)}. "
        f"For the quarter running from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}, their primary goal is: '{goal}'.\n\n"
        f"To help them, please generate a balanced and practical chore plan for this specific quarter.\n"
        f"1. **Incorporate the Goal:** A portion of the suggested chores should directly support their main goal.\n"
        f"2. **Maintain the Household:** The plan must also include a variety of general, recurring chores essential for a well-run home. Use the family's history of completed chores as a guide for the types of tasks and point values they find effective.\n"
        f"3. **Be Balanced:** Distribute a mix of personal responsibilities (like room cleaning), tasks for common areas (like the kitchen), and chores that promote teamwork. Suggest a variety of daily, weekly, and monthly recurrences.\n\n"
        f"Here are examples of their past successful chores and habits: {json.dumps(past_chores)}.\n\n"
        f"Give the plan a creative, motivational name like '{default_plan_name}'. "
        "For each chore, suggest a name, a brief description, a point value (5-50), and recurrence. "
        "Ensure the final output is a single, valid JSON object with this structure: "
        "`{\"plan_name\": string, \"suggested_chores\": [{\"name\": string, \"description\": string, \"points\": integer, \"type\": \"chore\", \"recurrence\": \"daily\"|\"weekly\"|\"monthly\"}]}`"
    )

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        plan_json_string = completion.choices[0].message.content
        plan_json = json.loads(plan_json_string)

        if 'plan_name' not in plan_json or not plan_json['plan_name']:
            plan_json['plan_name'] = default_plan_name

        plan_document_id = famjam_plans_collection.insert_one({
            'plan_data': plan_json,
            'goal': goal,
            'family_id': current_user.family_id,
            'status': 'draft',
            'start_date': start_date,
            'end_date': end_date,
            'created_at': datetime.utcnow()
        }).inserted_id

        plan_json['plan_id'] = str(plan_document_id)
        plan_json['start_date_str'] = start_date.strftime('%B %d, %Y')
        plan_json['end_date_str'] = end_date.strftime('%B %d, %Y')
        plan_json['family_children'] = children
        return jsonify(plan_json)
    except Exception as e:
        return jsonify({'error': f"Failed to get response from AI service: {e}"}), 503

@app.route('/api/famjam/apply', methods=['POST'])
@login_required
def apply_famjam_plan():
    if current_user.role != 'parent':
        return jsonify({"error": "Only parents can apply FamJam plans."}), 403

    plan_data = request.json
    plan_id_str = plan_data.get('plan_id')

    if not plan_data or 'suggested_chores' not in plan_data or not plan_id_str:
        return jsonify({'error': 'Invalid plan format received.'}), 400

    famjam_plans_collection.update_many(
        {'family_id': current_user.family_id, 'status': 'active'},
        {'$set': {'status': 'archived'}}
    )

    plan_data_to_save = {
        'plan_name': plan_data.get('plan_name'),
        'suggested_chores': plan_data.get('suggested_chores', [])
    }

    famjam_plans_collection.update_one(
        {'_id': ObjectId(plan_id_str), 'family_id': current_user.family_id},
        {'$set': {
            'status': 'active',
            'applied_at': datetime.utcnow(),
            'plan_data': plan_data_to_save
        }}
    )

    children = list(users_collection.find(
        {'family_id': current_user.family_id, 'role': 'child'},
        {'_id': 1}
    ))
    if not children:
        return jsonify({"error": "No children found in the family to assign chores to."}), 400

    child_ids = [str(c['_id']) for c in children]
    child_cycler = itertools.cycle(child_ids)

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    events_collection.delete_many({
        'family_id': current_user.family_id,
        'source': 'FamJamPlan',
        'source_type': 'generated',
        'status': 'assigned',
        'due_date': {'$gte': today}
    })

    end_date = today + timedelta(days=90)
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

        current_due_date = today
        while current_due_date < end_date:
            assigned_child_id = next(child_cycler)
            
            existing_event = events_collection.find_one({
                'family_id': current_user.family_id,
                'name': chore_template.get('name'),
                'due_date': current_due_date,
                'assigned_to': assigned_child_id
            })
            if existing_event:
                current_due_date += delta
                continue

            doc = {
                'name': chore_template.get('name'),
                'description': chore_template.get('description'),
                'points': int(chore_template.get('points', 0)),
                'type': 'chore',
                'family_id': current_user.family_id,
                'status': 'assigned',
                'created_at': datetime.utcnow(),
                'assigned_to': assigned_child_id,
                'due_date': current_due_date,
                'source': 'FamJamPlan',
                'source_type': 'generated'
            }
            new_events.append(doc)
            current_due_date += delta

    if not new_events:
        return jsonify({'status': 'warning', 'message': 'No new chores were scheduled. They may already exist for these dates.'})

    try:
        events_collection.insert_many(new_events)
        return jsonify({'status': 'success', 'message': f'{len(new_events)} chores have been scheduled for the next 90 days!'})
    except Exception as e:
        return jsonify({'error': f'Failed to save the plan to the database: {e}'}), 500
@app.route('/api/suggest-username', methods=['POST'])
def suggest_username():
    """Suggests unique usernames using GPT-4o-mini and database validation."""
    data = request.get_json() or {}
    name = data.get('name', '')

    # 1. Ask the AI for a larger batch of suggestions (e.g., 10)
    system_prompt = "You are a creative assistant that suggests fun, family-friendly usernames. Your response MUST be a valid JSON object with a 'suggestions' key containing an array of 10 unique strings."
    
    if name:
        user_prompt = f"Based on the name '{name}', suggest 10 creative and unique usernames for a family app. Avoid generic numbers."
    else:
        user_prompt = "Suggest 10 creative and unique usernames for a child in a family app. Use themes like animals, space, or nature."

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.9, # Increased for more diverse options
            max_tokens=250   # Increased to handle a larger response
        )
        suggestions_json_string = completion.choices[0].message.content
        potential_suggestions = json.loads(suggestions_json_string).get('suggestions', [])
        
        # 2. Filter the suggestions against the database to find unique ones
        unique_suggestions = []
        if potential_suggestions:
            for username in potential_suggestions:
                # Perform a case-insensitive check to see if the username is taken
                existing_user = users_collection.find_one(
                    {'username': regex.Regex(f'^{username}$', 'i')}
                )
                if not existing_user:
                    unique_suggestions.append(username)
                
                # 3. Stop once we have found 3 unique options
                if len(unique_suggestions) >= 3:
                    break
        
        return jsonify({'suggestions': unique_suggestions})

    except Exception as e:
        app.logger.error(f"Error during username suggestion: {e}")
        # Fallback in case of an API error
        return jsonify({'suggestions': ['User123', 'NewMember456', 'Player789']}), 500

@app.route('/share_invite')
@login_required
def share_invite():
    if current_user.role != 'parent':
        return jsonify({"error": "Not authorized"}), 403
    shareable_link_with_hash = f"{BASE_URL}/#invite={current_user.id}"
    return jsonify({"shareable_link": shareable_link_with_hash})

if __name__ == '__main__':
    app.run(debug=True, port=5001)

"""
gunicorn --workers 3 --bind 0.0.0.0:$PORT app:app
gunicorn --workers 3 --bind 0.0.0.0:5001 app:app
"""