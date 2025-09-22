# mChores Flask App
# To run this application:
# 1. Make sure you have MongoDB installed and running.
# 2. Install the required Python libraries:
#    pip install flask flask-login flask-bcrypt pymongo qrcode[pil]
# 3. Run the seed_db.py script once to populate the database:
#    python seed_db.py
# 4. Run this Flask application:
#    python app.py

import os
import io
from flask import Flask, render_template_string, request, redirect, url_for, flash, Response, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from bson.objectid import ObjectId
import qrcode

# --- App Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# --- Database Configuration ---
client = MongoClient('mongodb://localhost:27017/?retryWrites=true&w=majority&directConnection=true')
db = client['chore_app']
users_collection = db['users']
chores_collection = db['chores']
rewards_collection = db['rewards']

# --- Security & Login Configuration ---
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- User Model ---
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.email = user_data.get('email')
        self.username = user_data.get('username')
        self.password_hash = user_data['password_hash']
        self.role = user_data['role']
        self.family_id = user_data.get('family_id')
        self.points = user_data.get('points', 0)

    @staticmethod
    def get(user_id):
        user_data = users_collection.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(user_data)
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# --- HTML Templates ---
# Helper function to inject content into layout
def render_full_template(content_template, **kwargs):
    full_html = LAYOUT_TEMPLATE.replace('{% block content %}{% endblock %}', content_template)
    return render_template_string(full_html, **kwargs)


LAYOUT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>mChores - Family Chore Management</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; }
        .gradient-bg { background: linear-gradient(to right, #6366f1, #8b5cf6); }
    </style>
</head>
<body class="bg-gray-50 text-gray-800">
    <nav class="bg-white shadow-sm">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16">
                <div class="flex items-center">
                    <a href="{{ url_for('dashboard') }}" class="font-bold text-2xl text-indigo-600">
                        mChores
                    </a>
                </div>
                <div class="flex items-center space-x-4">
                    {% if current_user.is_authenticated %}
                        <span class="hidden sm:block text-sm font-medium text-gray-700">Welcome, {{ current_user.username or current_user.email }}!</span>
                        {% if current_user.role == 'parent' %}
                        <a href="{{ url_for('invite') }}" class="px-3 py-2 text-sm font-medium text-gray-700 rounded-md hover:bg-gray-100 transition">Invite</a>
                        {% endif %}
                        <a href="{{ url_for('logout') }}" class="px-3 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition">Log Out</a>
                    {% else %}
                        <a href="{{ url_for('login') }}" class="px-3 py-2 text-sm font-medium text-gray-700 rounded-md hover:bg-gray-100 transition">Log In</a>
                        <a href="{{ url_for('register_parent') }}" class="px-3 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition">Register</a>
                    {% endif %}
                </div>
            </div>
        </div>
    </nav>
    <main class="max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="p-4 mb-6 text-sm rounded-lg {{ 'bg-red-100 text-red-700' if category == 'error' else 'bg-green-100 text-green-700' }}" role="alert">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>
</body>
</html>
"""

LOGIN_TEMPLATE = """
{% block content %}
<div class="flex items-center justify-center min-h-[calc(100vh-200px)]">
    <div class="w-full max-w-sm p-8 space-y-6 bg-white rounded-xl shadow-lg">
        <h2 class="text-3xl font-bold text-center text-gray-900">Welcome Back!</h2>
        <form method="POST" action="{{ url_for('login') }}">
            <div class="space-y-4">
                <div>
                    <label for="email_or_username" class="block text-sm font-medium text-gray-700">Email or Username</label>
                    <input type="text" name="email_or_username" id="email_or_username" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500" required>
                </div>
                <div>
                    <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                    <input type="password" name="password" id="password" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500" required>
                </div>
            </div>
            <button type="submit" class="w-full mt-6 py-2 px-4 font-semibold text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition">Log In</button>
        </form>
    </div>
</div>
{% endblock %}
"""

REGISTER_PARENT_TEMPLATE = """
{% block content %}
<div class="flex items-center justify-center min-h-[calc(100vh-200px)]">
    <div class="w-full max-w-sm p-8 space-y-6 bg-white rounded-xl shadow-lg">
        <h2 class="text-3xl font-bold text-center text-gray-900">Create Parent Account</h2>
        <p class="text-center text-sm text-gray-600">Get started by creating a parent account for your family.</p>
        <form method="POST" action="{{ url_for('register_parent') }}">
            <div class="space-y-4">
                <div>
                    <label for="email" class="block text-sm font-medium text-gray-700">Email</label>
                    <input type="email" name="email" id="email" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500" required>
                </div>
                <div>
                    <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                    <input type="password" name="password" id="password" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500" required>
                </div>
            </div>
            <button type="submit" class="w-full mt-6 py-2 px-4 font-semibold text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition">Register</button>
        </form>
    </div>
</div>
{% endblock %}
"""

REGISTER_CHILD_TEMPLATE = """
{% block content %}
<div class="flex items-center justify-center min-h-[calc(100vh-200px)]">
    <div class="w-full max-w-sm p-8 space-y-6 bg-white rounded-xl shadow-lg">
        <h2 class="text-3xl font-bold text-center text-gray-900">Join Your Family!</h2>
        <p class="text-center text-sm text-gray-600">Create your username to start tracking chores and earning points.</p>
        <form method="POST" action="{{ url_for('register_child', invite_code=invite_code) }}">
            <div class="space-y-4">
                <div>
                    <label for="username" class="block text-sm font-medium text-gray-700">Username</label>
                    <input type="text" name="username" id="username" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500" required>
                </div>
                <div>
                    <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                    <input type="password" name="password" id="password" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500" required>
                </div>
            </div>
            <button type="submit" class="w-full mt-6 py-2 px-4 font-semibold text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition">Create Account</button>
        </form>
    </div>
</div>
{% endblock %}
"""

DASHBOARD_PARENT_TEMPLATE = """
{% block content %}
<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
    <div class="lg:col-span-2 space-y-8">
        <!-- Leaderboard & Insights -->
        <div class="bg-white p-6 rounded-xl shadow-lg">
            <h3 class="text-xl font-bold mb-4 text-gray-900">Family Leaderboard</h3>
            <div class="h-64">
                <canvas id="pointsChart"></canvas>
            </div>
        </div>
        
        <!-- Reward Requests -->
        <div class="bg-white p-6 rounded-xl shadow-lg">
            <h3 class="text-xl font-bold mb-4 text-gray-900">Reward Requests</h3>
            <div class="space-y-3">
            {% for reward in reward_requests %}
                <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <div>
                        <p class="font-semibold">{{ reward.name }} ({{ reward.points_cost }} pts)</p>
                        <p class="text-sm text-gray-600">Requested by {{ reward.requested_by_username }}</p>
                    </div>
                    {% if reward.status == 'requested' %}
                    <div class="flex space-x-2">
                        <a href="{{ url_for('handle_reward', reward_id=reward._id, action='approve') }}" class="px-3 py-1 text-xs font-medium text-white bg-green-500 rounded-full hover:bg-green-600">Approve</a>
                        <a href="{{ url_for('handle_reward', reward_id=reward._id, action='reject') }}" class="px-3 py-1 text-xs font-medium text-white bg-red-500 rounded-full hover:bg-red-600">Reject</a>
                    </div>
                    {% else %}
                    <span class="px-3 py-1 text-xs font-medium rounded-full {{ 'bg-green-100 text-green-800' if reward.status == 'approved' else 'bg-red-100 text-red-800' }}">{{ reward.status|capitalize }}</span>
                    {% endif %}
                </div>
            {% else %}
                <p class="text-sm text-gray-500">No pending reward requests.</p>
            {% endfor %}
            </div>
        </div>

        <!-- Chore List -->
        <div class="bg-white p-6 rounded-xl shadow-lg">
            <h3 class="text-xl font-bold mb-4 text-gray-900">Chore Management</h3>
             <div class="space-y-4">
            {% for chore in chores %}
            <div class="p-4 border border-gray-200 rounded-lg">
                <div class="flex flex-col sm:flex-row justify-between sm:items-center">
                    <div>
                        <div class="flex items-center gap-3">
                           <span class="px-2 py-1 text-xs font-semibold rounded-full {{ {'Daily': 'bg-blue-100 text-blue-800', 'Weekly': 'bg-purple-100 text-purple-800', 'Monthly': 'bg-pink-100 text-pink-800'}[chore.frequency] }}">{{ chore.frequency }}</span>
                           <h4 class="font-bold text-lg">{{ chore.name }} ({{ chore.points }} pts)</h4>
                        </div>
                        <p class="text-sm text-gray-600 mt-1">{{ chore.description }}</p>
                    </div>
                    <div class="mt-3 sm:mt-0 flex items-center justify-end">
                        {% if chore.status == 'pending' %}
                            <form method="POST" action="{{ url_for('assign_chore', chore_id=chore._id) }}" class="flex items-center space-x-2">
                                <select name="user_id" class="text-sm px-2 py-1 border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500">
                                    <option>Assign to...</option>
                                    {% for member in family_members %}
                                    <option value="{{ member._id }}">{{ member.username }}</option>
                                    {% endfor %}
                                </select>
                                <button type="submit" class="px-3 py-1 text-sm font-medium text-white bg-indigo-500 rounded-md hover:bg-indigo-600">Assign</button>
                            </form>
                        {% elif chore.status == 'assigned' %}
                            <span class="px-3 py-1 text-sm font-medium text-yellow-800 bg-yellow-100 rounded-full">Assigned to {{ chore.assigned_to_username }}</span>
                        {% elif chore.status == 'completed' %}
                            <a href="{{ url_for('approve_chore', chore_id=chore._id) }}" class="px-3 py-1 text-sm font-medium text-white bg-green-500 rounded-md hover:bg-green-600">Approve Completion</a>
                        {% elif chore.status == 'approved' %}
                            <span class="px-3 py-1 text-sm font-medium text-green-800 bg-green-100 rounded-full">Approved!</span>
                        {% endif %}
                    </div>
                </div>
            </div>
            {% else %}
            <p>No chores created yet. Add one!</p>
            {% endfor %}
        </div>
        </div>
    </div>

    <!-- Create Chore Section -->
    <div class="lg:col-span-1 bg-white p-6 rounded-xl shadow-lg h-fit">
        <h3 class="text-xl font-bold mb-4 text-gray-900">Create a New Chore</h3>
        <form method="POST" action="{{ url_for('create_chore') }}">
            <div class="space-y-4">
                <div>
                    <label for="name" class="block text-sm font-medium text-gray-700">Chore Name</label>
                    <input type="text" name="name" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md" required>
                </div>
                 <div>
                    <label for="frequency" class="block text-sm font-medium text-gray-700">Frequency</label>
                    <select name="frequency" id="frequency" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md">
                        <option value="Daily">Daily</option>
                        <option value="Weekly">Weekly</option>
                        <option value="Monthly">Monthly</option>
                    </select>
                </div>
                <div>
                    <label for="description" class="block text-sm font-medium text-gray-700">Description</label>
                    <textarea name="description" rows="3" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md"></textarea>
                </div>
                <div>
                    <label for="points" class="block text-sm font-medium text-gray-700">Points</label>
                    <input type="number" name="points" min="1" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md" required>
                </div>
                <button type="submit" class="w-full py-2 px-4 font-semibold text-white bg-indigo-600 rounded-md hover:bg-indigo-700">Add Chore</button>
            </div>
        </form>
    </div>
</div>
<script>
    const ctx = document.getElementById('pointsChart').getContext('2d');
    const familyData = {{ family_members_json|safe }};
    const labels = familyData.map(member => member.username);
    const data = familyData.map(member => member.points);
    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Points Earned',
                data: data,
                backgroundColor: 'rgba(99, 102, 241, 0.6)',
                borderColor: 'rgba(99, 102, 241, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
</script>
{% endblock %}
"""

DASHBOARD_CHILD_TEMPLATE = """
{% block content %}
<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
    <div class="lg:col-span-2 space-y-8">
        <!-- My Chores -->
        <div class="bg-white p-6 rounded-xl shadow-lg">
            <h2 class="text-2xl font-bold mb-4">My Assigned Chores</h2>
            <div class="space-y-4">
                {% for chore in chores %}
                <div class="p-4 border border-gray-200 rounded-lg flex flex-col sm:flex-row justify-between sm:items-center">
                    <div>
                        <div class="flex items-center gap-3">
                            <span class="px-2 py-1 text-xs font-semibold rounded-full {{ {'Daily': 'bg-blue-100 text-blue-800', 'Weekly': 'bg-purple-100 text-purple-800', 'Monthly': 'bg-pink-100 text-pink-800'}[chore.frequency] }}">{{ chore.frequency }}</span>
                            <h4 class="font-bold text-lg">{{ chore.name }} ({{ chore.points }} pts)</h4>
                        </div>
                        <p class="text-sm text-gray-600 mt-1">{{ chore.description }}</p>
                    </div>
                    <div class="mt-3 sm:mt-0">
                        {% if chore.status == 'assigned' %}
                            <a href="{{ url_for('complete_chore', chore_id=chore._id) }}" class="px-4 py-2 text-sm font-medium text-white bg-green-500 rounded-md hover:bg-green-600">Mark as Done</a>
                        {% elif chore.status == 'completed' %}
                            <span class="px-3 py-1 text-sm font-medium text-indigo-800 bg-indigo-100 rounded-full">Awaiting Approval</span>
                        {% elif chore.status == 'approved' %}
                            <span class="px-3 py-1 text-sm font-medium text-green-800 bg-green-100 rounded-full">Approved!</span>
                        {% endif %}
                    </div>
                </div>
                {% else %}
                <p class="text-gray-500">You have no assigned chores. Great job!</p>
                {% endfor %}
            </div>
        </div>
        
        <!-- Reward History -->
        <div class="bg-white p-6 rounded-xl shadow-lg">
            <h3 class="text-xl font-bold mb-4">My Rewards</h3>
             <div class="space-y-3">
            {% for reward in rewards %}
                <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <div>
                        <p class="font-semibold">{{ reward.name }} ({{ reward.points_cost }} pts)</p>
                    </div>
                    <span class="px-3 py-1 text-xs font-medium rounded-full {{ {'requested': 'bg-yellow-100 text-yellow-800', 'approved': 'bg-green-100 text-green-800', 'rejected': 'bg-red-100 text-red-800'}[reward.status] }}">{{ reward.status|capitalize }}</span>
                </div>
            {% else %}
                <p class="text-sm text-gray-500">You haven't requested any rewards yet.</p>
            {% endfor %}
            </div>
        </div>
    </div>

    <div class="lg:col-span-1 space-y-8">
        <!-- Points Card -->
        <div class="gradient-bg text-white p-6 rounded-xl shadow-lg text-center">
            <p class="text-lg font-medium opacity-80">My Points</p>
            <p class="text-5xl font-bold my-2">{{ current_user.points }}</p>
        </div>
        
        <!-- Request Reward -->
        <div class="bg-white p-6 rounded-xl shadow-lg">
            <h3 class="text-xl font-bold mb-4">Request a Reward</h3>
            <form method="POST" action="{{ url_for('request_reward') }}">
                <div class="space-y-4">
                    <div>
                        <label for="name" class="block text-sm font-medium text-gray-700">Reward Name</label>
                        <input type="text" name="name" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md" required placeholder="e.g., An hour of video games">
                    </div>
                    <div>
                        <label for="points_cost" class="block text-sm font-medium text-gray-700">Points Cost</label>
                        <input type="number" name="points_cost" min="1" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md" required placeholder="e.g., 200">
                    </div>
                    <button type="submit" class="w-full py-2 px-4 font-semibold text-white bg-indigo-600 rounded-md hover:bg-indigo-700">Submit Request</button>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
"""

INVITE_TEMPLATE = """
{% block content %}
<div class="bg-white p-8 rounded-xl shadow-lg text-center max-w-md mx-auto">
    <h2 class="text-3xl font-bold mb-2">Invite Your Family</h2>
    <p class="text-gray-600 mb-6">Share this code or scan the QR code to let your children join.</p>
    
    <div class="mb-6">
        <p class="text-lg font-medium text-gray-700">Your Invite Code</p>
        <p class="text-4xl font-mono p-3 my-2 bg-gray-100 rounded-md inline-block tracking-widest">{{ invite_code }}</p>
    </div>
    
    <div>
        <p class="text-lg font-medium mb-2">Scan with a Phone Camera</p>
        <img src="{{ url_for('qr_code') }}" alt="Invite QR Code" class="mx-auto border-4 border-gray-200 p-2 rounded-lg">
    </div>
</div>
{% endblock %}
"""

# --- Routes ---

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'parent':
        family_members = list(users_collection.find({'family_id': current_user.id}))
        
        family_user_map = {str(member['_id']): member['username'] for member in family_members if member.get('username')}
        chores_cursor = chores_collection.find({'family_id': current_user.id})
        chores = []
        for chore in chores_cursor:
            if chore.get('assigned_to'):
                chore['assigned_to_username'] = family_user_map.get(chore['assigned_to'], 'Unknown')
            chores.append(chore)
        
        reward_requests_cursor = rewards_collection.find({'family_id': current_user.id})
        reward_requests = []
        for reward in reward_requests_cursor:
            reward['requested_by_username'] = family_user_map.get(reward['requested_by_id'], 'Unknown')
            reward_requests.append(reward)

        family_members_json = jsonify(family_members).get_data(as_text=True)
            
        return render_full_template(DASHBOARD_PARENT_TEMPLATE, chores=chores, family_members=family_members, reward_requests=reward_requests, family_members_json=family_members_json)
    else: # Child
        chores = list(chores_collection.find({'assigned_to': current_user.id}))
        rewards = list(rewards_collection.find({'requested_by_id': current_user.id}))
        return render_full_template(DASHBOARD_CHILD_TEMPLATE, chores=chores, rewards=rewards)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        identifier = request.form['email_or_username']
        user_data = users_collection.find_one({'$or': [{'email': identifier}, {'username': identifier}]})
        
        if user_data and bcrypt.check_password_hash(user_data['password_hash'], request.form['password']):
            user = User(user_data)
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'error')
    return render_full_template(LOGIN_TEMPLATE)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register/parent', methods=['GET', 'POST'])
def register_parent():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if users_collection.find_one({'email': email}):
            flash('Email address already in use.', 'error')
            return redirect(url_for('register_parent'))
        
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user_id = users_collection.insert_one({
            'email': email,
            'password_hash': hashed_password,
            'role': 'parent'
        }).inserted_id
        
        users_collection.update_one({'_id': user_id}, {'$set': {'family_id': str(user_id), 'points': 0}})
        
        flash('Parent account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_full_template(REGISTER_PARENT_TEMPLATE)
    
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

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        users_collection.insert_one({
            'username': username,
            'password_hash': hashed_password,
            'role': 'child',
            'family_id': invite_code,
            'points': 0
        })
        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_full_template(REGISTER_CHILD_TEMPLATE, invite_code=invite_code)

@app.route('/invite')
@login_required
def invite():
    if current_user.role != 'parent':
        return redirect(url_for('dashboard'))
    return render_full_template(INVITE_TEMPLATE, invite_code=current_user.id)

@app.route('/qr_code')
@login_required
def qr_code():
    if current_user.role != 'parent':
        return Response(status=403)
    
    invite_url = url_for('register_child', invite_code=current_user.id, _external=True)
    img = qrcode.make(invite_url)
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return Response(buf, mimetype='image/png')
    
# --- Chore & Reward Routes ---
@app.route('/chore/create', methods=['POST'])
@login_required
def create_chore():
    if current_user.role == 'parent':
        chores_collection.insert_one({
            'name': request.form['name'],
            'description': request.form['description'],
            'points': int(request.form['points']),
            'frequency': request.form['frequency'],
            'family_id': current_user.family_id,
            'status': 'pending' 
        })
        flash('Chore created!', 'success')
    return redirect(url_for('dashboard'))
    
@app.route('/chore/assign/<chore_id>', methods=['POST'])
@login_required
def assign_chore(chore_id):
    if current_user.role == 'parent':
        user_id_to_assign = request.form.get('user_id')
        if user_id_to_assign:
            chores_collection.update_one(
                {'_id': ObjectId(chore_id), 'family_id': current_user.family_id},
                {'$set': {'assigned_to': user_id_to_assign, 'status': 'assigned'}}
            )
            flash('Chore assigned.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/chore/complete/<chore_id>')
@login_required
def complete_chore(chore_id):
    if current_user.role == 'child':
        chores_collection.update_one(
            {'_id': ObjectId(chore_id), 'assigned_to': current_user.id},
            {'$set': {'status': 'completed'}}
        )
        flash('Chore marked as complete! Awaiting approval.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/chore/approve/<chore_id>')
@login_required
def approve_chore(chore_id):
    if current_user.role == 'parent':
        chore = chores_collection.find_one_and_update(
            {'_id': ObjectId(chore_id), 'family_id': current_user.family_id},
            {'$set': {'status': 'approved'}}
        )
        if chore and chore.get('assigned_to'):
            users_collection.update_one(
                {'_id': ObjectId(chore['assigned_to'])},
                {'$inc': {'points': chore['points']}}
            )
            flash(f"Chore approved! {chore['points']} points awarded.", 'success')
    return redirect(url_for('dashboard'))

@app.route('/reward/request', methods=['POST'])
@login_required
def request_reward():
    if current_user.role == 'child':
        points_cost = int(request.form['points_cost'])
        if current_user.points < points_cost:
            flash("You don't have enough points for that reward!", 'error')
            return redirect(url_for('dashboard'))
            
        rewards_collection.insert_one({
            'name': request.form['name'],
            'points_cost': points_cost,
            'family_id': current_user.family_id,
            'requested_by_id': current_user.id,
            'status': 'requested'
        })
        flash('Reward requested! Your parent will review it.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/reward/handle/<reward_id>/<action>')
@login_required
def handle_reward(reward_id, action):
    if current_user.role == 'parent':
        reward = rewards_collection.find_one({'_id': ObjectId(reward_id), 'family_id': current_user.family_id})
        if not reward:
            flash("Reward not found.", 'error')
            return redirect(url_for('dashboard'))

        if action == 'approve':
            # Check if child still has enough points
            child = users_collection.find_one({'_id': ObjectId(reward['requested_by_id'])})
            if child['points'] >= reward['points_cost']:
                rewards_collection.update_one({'_id': reward['_id']}, {'$set': {'status': 'approved'}})
                users_collection.update_one({'_id': child['_id']}, {'$inc': {'points': -reward['points_cost']}})
                flash('Reward approved and points deducted.', 'success')
            else:
                flash("Child no longer has enough points. Reward cannot be approved.", 'error')
                rewards_collection.update_one({'_id': reward['_id']}, {'$set': {'status': 'rejected'}})
        
        elif action == 'reject':
            rewards_collection.update_one({'_id': reward['_id']}, {'$set': {'status': 'rejected'}})
            flash('Reward rejected.', 'success')
            
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    app.run(debug=True, port=5001)


"""
 gunicorn --workers 3 --bind 0.0.0.0:$PORT app:app
"""