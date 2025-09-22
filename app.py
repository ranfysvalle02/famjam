import os  
import io  
import json  
from datetime import datetime, timedelta, date  
from flask import Flask, render_template_string, request, redirect, url_for, flash, Response, jsonify  
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user  
from flask_bcrypt import Bcrypt  
from pymongo import MongoClient, ASCENDING, DESCENDING  
from bson.objectid import ObjectId  
from bson import json_util, regex  
import qrcode  
from dateutil.relativedelta import relativedelta  
  
app = Flask(__name__)  
# IMPORTANT: Change this for production usage  
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a-super-secret-key-that-you-should-change')  
  
# --- Mongo setup ---  
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')  
client = MongoClient(MONGO_URI)  
db = client['mchores_app']  
  
users_collection = db['users']             # user documents  
events_collection = db['events']           # chores/habits  
rewards_collection = db['rewards']         # reward requests from child  
transactions_collection = db['transactions'] # logs each reward spend attempt  
  
# Recommended indexes  
users_collection.create_index([('email', ASCENDING)], unique=True, sparse=True)  
users_collection.create_index([('username', ASCENDING), ('family_id', ASCENDING)], unique=True, sparse=True)  
events_collection.create_index([('family_id', ASCENDING), ('due_date', ASCENDING)])  
  
bcrypt = Bcrypt(app)  
login_manager = LoginManager()  
login_manager.init_app(app)  
login_manager.login_view = 'login'  
  
  
# --- Models ---  
class User(UserMixin):  
    """  
    Each user has:  
      - points: current available points that can be spent  
      - lifetime_points: total points ever earned (never decreased)  
    """  
    def __init__(self, user_data):  
        self.id = str(user_data['_id'])  
        self.email = user_data.get('email')  
        self.username = user_data.get('username')  
        self.password_hash = user_data['password_hash']  
        self.role = user_data['role']  # 'parent' or 'child'  
        self.family_id = user_data.get('family_id')  
        self.points = user_data.get('points', 0)  # Current available points  
        self.lifetime_points = user_data.get('lifetime_points', 0)  # All-time earned  
  
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
  
  
def render_full_template(content_template, **kwargs):  
    """  
    Replaces the content block in LAYOUT_TEMPLATE with a sub-template  
    and returns the final combined HTML.  
    """  
    return render_template_string(  
        LAYOUT_TEMPLATE.replace('{% block content %}{% endblock %}', content_template),  
        **kwargs  
    )  
  
# --- Main Layout Template (tsParticles background, Tailwind, etc.) ---  
LAYOUT_TEMPLATE = """  
<!DOCTYPE html>  
<html lang="en">  
<head>  
  <meta charset="UTF-8">  
  <!-- Ensure mobile friendliness -->  
  <meta name="viewport" content="width=device-width, initial-scale=1.0">  
  <title>mChores - Family Chore & Habit Management</title>  
  
  <!-- Tailwind + Chart.js + FullCalendar + tsParticles -->  
  <script src="https://cdn.tailwindcss.com"></script>  
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>  
  <script src='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.13/index.global.min.js'></script>  
  <script src="https://cdn.jsdelivr.net/npm/tsparticles@2/tsparticles.bundle.min.js"></script>  
  
  <script>  
    document.addEventListener("DOMContentLoaded", function() {  
      // Slightly animated background using tsParticles  
      tsParticles.load("tsparticles", {  
        fpsLimit: 60,  
        background: { color: "transparent" },  
        particles: {  
          number: { value: 50, density: { enable: true, value_area: 800 } },  
          color: { value: "#ec4899" },  
          shape: { type: "circle" },  
          opacity: {  
            value: 0.7,  
            random: true,  
            anim: {  
              enable: true,  
              speed: 1,  
              opacity_min: 0.2,  
              sync: false  
            }  
          },  
          size: {  
            value: 3,  
            random: true,  
            anim: {  
              enable: true,  
              speed: 3,  
              size_min: 0.5,  
              sync: false  
            }  
          },  
          move: {  
            enable: true,  
            speed: 1,  
            random: true,  
            out_mode: "out"  
          },  
          line_linked: { enable: false }  
        },  
        interactivity: {  
          detectsOn: "canvas",  
          events: {  
            onhover: { enable: true, mode: "repulse" },  
            onclick: { enable: true, mode: "push" },  
            resize: true  
          },  
          modes: {  
            repulse: { distance: 100, duration: 0.4 },  
            push: { quantity: 4 }  
          }  
        },  
        retina_detect: true  
      });  
    });  
  
    // Tailwind extension  
    tailwind.config = {  
      theme: {  
        extend: {  
          colors: {  
            primary: {  
              '50': '#eff6ff','100': '#dbeafe','200': '#bfdbfe','300': '#93c5fd','400': '#60a5fa',  
              '500': '#3b82f6','600': '#2563eb','700': '#1d4ed8','800': '#1e40af','900': '#1e3a8a'  
            },  
            secondary: {  
              '50': '#fdf2f8','100': '#fce7f3','200': '#fbcfe8','300': '#f9a8d4','400': '#f472b6',  
              '500': '#ec4899','600': '#db2777','700': '#be185d','800': '#9d174d','900': '#831843'  
            }  
          }  
        }  
      }  
    }  
  </script>  
  
  <style>  
    body {  
      font-family: 'Inter', sans-serif;  
      background-color: #f3f4f6;  
    }  
    .gradient-text {  
      background: linear-gradient(to right, #4f46e5, #ec4899);  
      -webkit-background-clip: text;  
      -webkit-text-fill-color: transparent;  
    }  
    #tsparticles {  
      position: absolute; inset: 0; z-index: -10;  
    }  
    .fc .fc-button-primary {  
      background-color: #2563eb; border-color: #2563eb;  
      transition: background-color 0.2s;  
    }  
    .fc .fc-button-primary:hover {  
      background-color: #1d4ed8; border-color: #1d4ed8;  
    }  
    .fc .fc-daygrid-day.fc-day-today {  
      background-color: rgba(59, 130, 246, 0.08);  
    }  
  
    @keyframes fadeIn {  
      from { opacity: 0; transform: translateY(-10px); }  
      to   { opacity: 1; transform: translateY(0); }  
    }  
    .fade-in { animation: fadeIn 0.5s ease-in-out forwards; }  
  
    @keyframes scaleUp {  
      from { transform: scale(0.95); opacity: 0; }  
      to   { transform: scale(1);   opacity: 1; }  
    }  
    .modal-content {  
      animation: scaleUp 0.3s cubic-bezier(0.165, 0.84, 0.44, 1) forwards;  
    }  
  
    .custom-scrollbar::-webkit-scrollbar { width: 6px; }  
    .custom-scrollbar::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 10px; }  
    .custom-scrollbar::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 10px; }  
    .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #9ca3af; }  
  
    .tab-button.active {  
      border-color: #2563eb;  
      color: #2563eb;  
      background-color: #eff6ff;  
    }  
    .tab-content { display: none; }  
    .tab-content.active { display: block; }  
  </style>  
</head>  
<body class="text-gray-800 antialiased relative">  
  <!-- Particle background container -->  
  <div id="tsparticles"></div>  
  
  <!-- Navigation Bar -->  
  <nav class="bg-white/80 backdrop-blur-md shadow-sm sticky top-0 z-50">  
    <div class="max-w-screen-xl mx-auto px-4 sm:px-6 lg:px-8">  
      <div class="flex justify-between items-center h-16">  
        <!-- Left side: branding -->  
        <div class="flex items-center space-x-8">  
          <a href="{{ url_for('index') }}" class="font-extrabold text-2xl gradient-text">  
            mChores  
          </a>  
        </div>  
        <!-- Right side: desktop nav -->  
        <div class="hidden sm:flex items-center space-x-2">  
          {% if current_user.is_authenticated %}  
            <div class="hidden sm:flex items-center space-x-1 bg-gray-100 rounded-full p-1">  
              <a href="{{ url_for('family_dashboard') }}"  
                 class="px-3 py-1 text-sm font-medium rounded-full transition-colors  
                        {{ 'bg-white text-gray-800 shadow-sm' if request.endpoint == 'family_dashboard' else 'text-gray-600 hover:text-gray-900' }}">  
                Family Hub  
              </a>  
              <a href="{{ url_for('personal_dashboard') }}"  
                 class="px-3 py-1 text-sm font-medium rounded-full transition-colors  
                        {{ 'bg-white text-gray-800 shadow-sm' if request.endpoint == 'personal_dashboard' else 'text-gray-600 hover:text-gray-900' }}">  
                {% if current_user.role == 'parent' %}Manage Tasks{% else %}My Tasks{% endif %}  
              </a>  
              <a href="{{ url_for('calendar_focus') }}"  
                 class="px-3 py-1 text-sm font-medium rounded-full transition-colors  
                        {{ 'bg-white text-gray-800 shadow-sm' if request.endpoint == 'calendar_focus' else 'text-gray-600 hover:text-gray-900' }}">  
                Calendar  
              </a>  
            </div>  
            <div class="flex items-center space-x-4 ml-4">  
              <span class="hidden sm:block text-sm font-medium text-gray-700">  
                Hi, {{ current_user.username }}!  
              </span>  
              {% if current_user.role == 'parent' %}  
              <a href="{{ url_for('invite') }}"  
                 class="hidden sm:block p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-full transition-colors">  
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none"  
                     viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">  
                  <path stroke-linecap="round" stroke-linejoin="round"  
                        d="M18 9v3m0 0v3m0-3h3m-3   
                           0h-3m-2-5a4 4 0   
                           11-8 0 4 4 0   
                           018 0zM3 20a6 6 0   
                           0112 0v1H3v-1z"/>  
                </svg>  
              </a>  
              {% endif %}  
              <a href="{{ url_for('logout') }}"  
                 class="px-4 py-2 text-sm font-semibold text-white bg-blue-600 rounded-full  
                        hover:bg-blue-700 focus:outline-none focus:ring-2  
                        focus:ring-offset-2 focus:ring-blue-500 transition shadow-sm">  
                Log Out  
              </a>  
            </div>  
          {% else %}  
            <a href="{{ url_for('login') }}"  
               class="px-4 py-2 text-sm font-medium text-gray-700 rounded-full  
                      hover:bg-gray-100 transition">  
              Log In  
            </a>  
            <a href="{{ url_for('register_parent') }}"  
               class="px-4 py-2 text-sm font-semibold text-white bg-blue-600  
                      rounded-full hover:bg-blue-700 transition shadow-sm">  
              Register  
            </a>  
          {% endif %}  
        </div>  
        <!-- Hamburger for mobile -->  
        <div class="sm:hidden flex items-center">  
          <button id="mobile-menu-button"  
                  class="p-2 rounded-md text-gray-600 hover:text-gray-800  
                         focus:outline-none focus:ring-2 focus:ring-offset-2  
                         focus:ring-blue-500 transition">  
            <svg class="h-6 w-6" stroke="currentColor" fill="none"  
                 viewBox="0 0 24 24" stroke-width="2">  
              <path stroke-linecap="round" stroke-linejoin="round"  
                    d="M4 6h16M4 12h16M4 18h16"/>  
            </svg>  
          </button>  
        </div>  
      </div>  
    </div>  
    <!-- Mobile nav -->  
    <div id="mobileMenu" class="hidden sm:hidden bg-white shadow-lg">  
      <div class="px-4 pt-4 pb-4 space-y-2">  
        {% if current_user.is_authenticated %}  
          <a href="{{ url_for('family_dashboard') }}"  
             class="block px-3 py-2 rounded-md text-sm font-medium  
                    text-gray-700 hover:bg-gray-100">  
            Family Hub  
          </a>  
          <a href="{{ url_for('personal_dashboard') }}"  
             class="block px-3 py-2 rounded-md text-sm font-medium  
                    text-gray-700 hover:bg-gray-100">  
            {% if current_user.role == 'parent' %}Manage Tasks{% else %}My Tasks{% endif %}  
          </a>  
          <a href="{{ url_for('calendar_focus') }}"  
             class="block px-3 py-2 rounded-md text-sm font-medium  
                    text-gray-700 hover:bg-gray-100">  
            Calendar  
          </a>  
          {% if current_user.role == 'parent' %}  
          <a href="{{ url_for('invite') }}"  
             class="block px-3 py-2 rounded-md text-sm font-medium  
                    text-gray-700 hover:bg-gray-100">  
            Invite  
          </a>  
          {% endif %}  
          <a href="{{ url_for('logout') }}"  
             class="block px-3 py-2 rounded-md text-sm font-medium  
                    text-blue-600 hover:bg-gray-100">  
            Log Out  
          </a>  
        {% else %}  
          <a href="{{ url_for('login') }}"  
             class="block px-3 py-2 rounded-md text-sm font-medium  
                    text-gray-700 hover:bg-gray-100">  
            Log In  
          </a>  
          <a href="{{ url_for('register_parent') }}"  
             class="block px-3 py-2 rounded-md text-sm font-medium  
                    text-white bg-blue-600 hover:bg-blue-700">  
            Register  
          </a>  
        {% endif %}  
      </div>  
    </div>  
  </nav>  
  
  <main class="max-w-screen-xl mx-auto py-8 px-4 sm:px-6 lg:px-8">  
    <!-- Flash messages -->  
    {% with messages = get_flashed_messages(with_categories=true) %}  
      {% if messages %}  
        {% for category, message in messages %}  
          <div class="p-4 mb-6 text-sm rounded-lg shadow-md  
                      {{ 'bg-red-100 text-red-800 border border-red-200' if category == 'error'  
                         else 'bg-green-100 text-green-800 border border-green-200' }}"  
               role="alert">  
            <span class="font-medium">{{ message }}</span>  
          </div>  
        {% endfor %}  
      {% endif %}  
    {% endwith %}  
    <div class="fade-in">  
      {% block content %}{% endblock %}  
    </div>  
  </main>  
  
  <script>  
    // Toggle mobile menu  
    const mobileMenuButton = document.getElementById("mobile-menu-button");  
    const mobileMenu = document.getElementById("mobileMenu");  
    mobileMenuButton.addEventListener("click", () => {  
      mobileMenu.classList.toggle("hidden");  
    });  
  </script>  
</body>  
</html>  
"""  
  
# --- Subtemplates for various pages ---  
  
LOGIN_TEMPLATE = """{% block content %}  
<div class="flex items-center justify-center min-h-[calc(100vh-250px)]">  
  <div class="w-full max-w-md p-8 space-y-6 bg-white rounded-2xl shadow-xl">  
    <div class="text-center">  
      <h1 class="text-4xl font-extrabold gradient-text">Welcome Back</h1>  
      <p class="mt-2 text-gray-600">Log in to manage your family's tasks.</p>  
    </div>  
    <form method="POST" action="{{ url_for('login') }}" class="space-y-6">  
      <div>  
        <label for="email_or_username" class="block text-sm font-medium text-gray-700">  
          Email or Username  
        </label>  
        <input type="text" name="email_or_username" id="email_or_username"  
               required  
               class="mt-1 block w-full px-4 py-3 bg-gray-50  
                      border border-gray-300 rounded-lg shadow-sm  
                      focus:outline-none focus:ring-blue-500  
                      focus:border-blue-500 transition">  
      </div>  
      <div>  
        <label for="password" class="block text-sm font-medium text-gray-700">  
          Password  
        </label>  
        <input type="password" name="password" id="password"  
               required  
               class="mt-1 block w-full px-4 py-3 bg-gray-50  
                      border border-gray-300 rounded-lg shadow-sm  
                      focus:outline-none focus:ring-blue-500  
                      focus:border-blue-500 transition">  
      </div>  
      <button type="submit"  
              class="w-full py-3 px-4 font-semibold text-white bg-blue-600  
                     rounded-lg hover:bg-blue-700 focus:outline-none  
                     focus:ring-2 focus:ring-offset-2 focus:ring-blue-500  
                     transition-transform transform hover:scale-105 shadow-lg">  
        Log In  
      </button>  
    </form>  
    <p class="text-center text-sm text-gray-600 mt-2">  
      Don't have an account?   
      <a href="{{ url_for('register_parent') }}"  
         class="font-medium text-blue-600 hover:text-blue-500">  
         Register as a Parent  
      </a>  
    </p>  
  </div>  
</div>  
{% endblock %}  
"""  
  
REGISTER_PARENT_TEMPLATE = """{% block content %}  
<div class="flex items-center justify-center min-h-[calc(100vh-250px)]">  
  <div class="w-full max-w-md p-8 space-y-6 bg-white rounded-2xl shadow-xl">  
    <div class="text-center">  
      <h1 class="text-4xl font-extrabold gradient-text">Create Your Family Hub</h1>  
      <p class="mt-2 text-gray-600">Start by creating a parent account.</p>  
    </div>  
    <form method="POST" action="{{ url_for('register_parent') }}" class="space-y-6">  
      <div>  
        <label for="username" class="block text-sm font-medium text-gray-700">  
          Your Name / Username  
        </label>  
        <input type="text" name="username" id="username"  
               required  
               class="mt-1 block w-full px-4 py-3 bg-gray-50  
                      border border-gray-300 rounded-lg shadow-sm  
                      focus:outline-none focus:ring-blue-500  
                      focus:border-blue-500 transition">  
      </div>  
      <div>  
        <label for="email" class="block text-sm font-medium text-gray-700">  
          Email Address  
        </label>  
        <input type="email" name="email" id="email"  
               required  
               class="mt-1 block w-full px-4 py-3 bg-gray-50  
                      border border-gray-300 rounded-lg shadow-sm  
                      focus:outline-none focus:ring-blue-500  
                      focus:border-blue-500 transition">  
      </div>  
      <div>  
        <label for="password" class="block text-sm font-medium text-gray-700">  
          Password  
        </label>  
        <input type="password" name="password" id="password"  
               required  
               class="mt-1 block w-full px-4 py-3 bg-gray-50  
                      border border-gray-300 rounded-lg shadow-sm  
                      focus:outline-none focus:ring-blue-500  
                      focus:border-blue-500 transition">  
      </div>  
      <button type="submit"  
              class="w-full py-3 px-4 font-semibold text-white bg-blue-600  
                     rounded-lg hover:bg-blue-700 focus:outline-none  
                     focus:ring-2 focus:ring-offset-2 focus:ring-blue-500  
                     transition-transform transform hover:scale-105 shadow-lg">  
        Create Account  
      </button>  
    </form>  
    <p class="text-center text-sm text-gray-600 mt-2">  
      Already have an account?  
      <a href="{{ url_for('login') }}"  
         class="font-medium text-blue-600 hover:text-blue-500">  
        Log In  
      </a>  
    </p>  
  </div>  
</div>  
{% endblock %}  
"""  
  
REGISTER_CHILD_TEMPLATE = """{% block content %}  
<div class="flex items-center justify-center min-h-[calc(100vh-250px)]">  
  <div class="w-full max-w-md p-8 space-y-6 bg-white rounded-2xl shadow-xl">  
    <div class="text-center">  
      <h1 class="text-4xl font-extrabold gradient-text">Join Your Family!</h1>  
      <p class="mt-2 text-gray-600">Create a username and password to get started.</p>  
    </div>  
    <form method="POST" action="{{ url_for('register_child', invite_code=invite_code) }}" class="space-y-6">  
      <div>  
        <label for="username" class="block text-sm font-medium text-gray-700">  
          Username  
        </label>  
        <input type="text" name="username" id="username"  
               required  
               class="mt-1 block w-full px-4 py-3 bg-gray-50  
                      border border-gray-300 rounded-lg shadow-sm  
                      focus:outline-none focus:ring-blue-500  
                      focus:border-blue-500 transition">  
      </div>  
      <div>  
        <label for="password" class="block text-sm font-medium text-gray-700">  
          Password  
        </label>  
        <input type="password" name="password" id="password"  
               required  
               class="mt-1 block w-full px-4 py-3 bg-gray-50  
                      border border-gray-300 rounded-lg shadow-sm  
                      focus:outline-none focus:ring-blue-500  
                      focus:border-blue-500 transition">  
      </div>  
      <button type="submit"  
              class="w-full py-3 px-4 font-semibold text-white bg-blue-600  
                     rounded-lg hover:bg-blue-700 focus:outline-none  
                     focus:ring-2 focus:ring-offset-2 focus:ring-blue-500  
                     transition-transform transform hover:scale-105 shadow-lg">  
        Join Family  
      </button>  
    </form>  
  </div>  
</div>  
{% endblock %}  
"""  
  
DASHBOARD_PARENT_TEMPLATE = """{% block content %}  
<div class="bg-white p-6 sm:p-8 rounded-2xl shadow-xl">  
  <div class="border-b border-gray-200 mb-6">  
    <nav class="-mb-px flex space-x-6" id="tabs">  
      <button onclick="switchTab(event, 'createTask')"  
              class="tab-button active py-4 px-1 border-b-2 font-medium  
                     text-sm text-gray-500 hover:text-gray-700 hover:border-gray-300">  
        Create Task  
      </button>  
      <button onclick="switchTab(event, 'pendingTasks')"  
              class="tab-button py-4 px-1 border-b-2 font-medium  
                     text-sm text-gray-500 hover:text-gray-700 hover:border-gray-300">  
        Pending Tasks  
      </button>  
      <button onclick="switchTab(event, 'rewardRequests')"  
              class="tab-button py-4 px-1 border-b-2 font-medium  
                     text-sm text-gray-500 hover:text-gray-700 hover:border-gray-300">  
        Reward Requests  
      </button>  
      <button onclick="switchTab(event, 'spendHistory')"  
              class="tab-button py-4 px-1 border-b-2 font-medium  
                     text-sm text-gray-500 hover:text-gray-700 hover:border-gray-300">  
        Spend History  
      </button>  
    </nav>  
  </div>  
  
  <div>  
    <!-- TAB 1: Create Task -->  
    <div id="createTask" class="tab-content active">  
      <h3 class="text-2xl font-bold mb-6 text-gray-900">Easily Assign a Chore or Habit</h3>  
      <form method="POST" action="{{ url_for('create_event') }}">  
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">  
          <div class="md:col-span-2">  
            <label for="name" class="block text-sm font-medium text-gray-700">  
              Task / Habit Name  
            </label>  
            <input type="text" name="name" placeholder="e.g. Clean your room"  
                   class="mt-1 block w-full px-4 py-3 bg-gray-50 border-gray-300  
                          rounded-lg focus:ring-blue-500 focus:border-blue-500"  
                   required>  
          </div>  
          <div class="md:col-span-2">  
            <label for="description" class="block text-sm font-medium text-gray-700">  
              Description (Optional)  
            </label>  
            <textarea name="description" rows="3" placeholder="e.g. Tidy surfaces, vacuum, dust..."  
                      class="mt-1 block w-full px-4 py-3 bg-gray-50 border-gray-300  
                             rounded-lg focus:ring-blue-500 focus:border-blue-500"></textarea>  
          </div>  
          <div>  
            <label for="type" class="block text-sm font-medium text-gray-700">  
              Type  
            </label>  
            <select name="type"  
                    class="mt-1 block w-full px-4 py-3 bg-gray-50 border-gray-300  
                           rounded-lg focus:ring-blue-500 focus:border-blue-500">  
              <option value="chore">Chore (One-time or repeating)</option>  
              <option value="habit">Habit (Daily checks for a streak)</option>  
            </select>  
          </div>  
          <div>  
            <label for="points" class="block text-sm font-medium text-gray-700">  
              Points Value  
            </label>  
            <input type="number" name="points" min="1" placeholder="e.g. 50"  
                   class="mt-1 block w-full px-4 py-3 bg-gray-50 border-gray-300  
                          rounded-lg focus:ring-blue-500 focus:border-blue-500"  
                   required>  
          </div>  
          <div>  
            <label for="assigned_to" class="block text-sm font-medium text-gray-700">  
              Assign To  
            </label>  
            <select name="assigned_to"  
                    class="mt-1 block w-full px-4 py-3 bg-gray-50 border-gray-300  
                           rounded-lg focus:ring-blue-500 focus:border-blue-500" required>  
              <option value="">Select a child...</option>  
              {% for member in family_members if member.role == 'child' %}  
              <option value="{{ member._id }}">{{ member.username }}</option>  
              {% endfor %}  
            </select>  
          </div>  
          <div>  
            <label for="due_date" class="block text-sm font-medium text-gray-700">  
              Start Date  
            </label>  
            <input type="date" name="due_date"  
                   class="mt-1 block w-full px-4 py-3 bg-gray-50 border-gray-300  
                          rounded-lg focus:ring-blue-500 focus:border-blue-500"  
                   required>  
          </div>  
        </div>  
        <button type="submit"  
                class="w-full md:w-auto mt-8 py-3 px-8 font-semibold text-white bg-blue-600  
                       rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2  
                       focus:ring-offset-2 focus:ring-blue-500 transition-transform  
                       transform hover:scale-105 shadow-lg">  
          Add Task  
        </button>  
      </form>  
    </div>  
  
    <!-- TAB 2: Pending Tasks -->  
    <div id="pendingTasks" class="tab-content">  
      <h3 class="text-2xl font-bold mb-6 text-gray-900">Review Submitted Tasks</h3>  
      <div class="space-y-4">  
        {% for event in events %}  
          {% if event.status == 'completed' %}  
          <div class="flex items-center justify-between p-4 bg-gray-50 border border-gray-200  
                      rounded-lg hover:shadow-md transition-shadow">  
            <div class="flex items-center space-x-4">  
              <span class="p-2.5 rounded-full  
                           {{ 'bg-pink-100' if event.type == 'habit'  
                              else 'bg-purple-100' }}">  
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6  
                           {{ 'text-pink-600' if event.type == 'habit'  
                              else 'text-purple-600' }}"  
                     fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">  
                  <path stroke-linecap="round" stroke-linejoin="round"  
                        d="{{ 'M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364  
                             l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12  
                             7.636l-1.318-1.318a4.5 4.5 0   
                             00-6.364 0z'  
                           if event.type == 'habit'  
                           else 'M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286  
                                  6.857L21 12l-5.714 2.143L13 21l-2.286  
                                  -6.857L5 12l5.714-2.143L13 3z' }}" />  
                </svg>  
              </span>  
              <div>  
                <p class="font-semibold text-gray-800">{{ event.name }}</p>  
                <p class="text-sm text-gray-500">  
                  Submitted by <span class="font-medium">{{ member_map[event.assigned_to] }}</span>  
                  &middot; Worth <span class="font-medium">{{ event.points }} pts</span>  
                </p>  
              </div>  
            </div>  
            <a href="{{ url_for('approve_event', event_id=event._id) }}"  
               class="flex items-center space-x-2 px-4 py-2 text-sm font-semibold  
                      text-white bg-green-500 rounded-full hover:bg-green-600  
                      transition-transform transform hover:scale-105">  
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none"  
                   viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">  
                <path stroke-linecap="round" stroke-linejoin="round"  
                      d="M5 13l4 4L19 7"/>  
              </svg>  
              <span>Approve</span>  
            </a>  
          </div>  
          {% endif %}  
        {% else %}  
          <p class="text-center py-8 text-gray-500">  
            No tasks are currently pending approval. Great job, team!  
          </p>  
        {% endfor %}  
      </div>  
    </div>  
  
    <!-- TAB 3: Reward Requests -->  
    <div id="rewardRequests" class="tab-content">  
      <h3 class="text-2xl font-bold mb-6 text-gray-900">Review Reward Requests</h3>  
      <p class="text-sm text-gray-600 mb-4">  
        If a reward is not suitable, reject to refund the child's points. Otherwise, approve to confirm the spend.  
      </p>  
      <div class="space-y-4">  
        {% for reward in reward_requests %}  
          <div class="flex items-center justify-between p-4 bg-gray-50 border border-gray-200  
                      rounded-lg hover:shadow-md transition-shadow">  
            <div class="flex items-center space-x-4">  
              <span class="p-2.5 rounded-full bg-yellow-100">  
                <svg xmlns="http://www.w3.org/2000/svg"  
                     class="h-6 w-6 text-yellow-600" fill="none"  
                     viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">  
                  <path stroke-linecap="round" stroke-linejoin="round"  
                        d="M12 8v4l3 3m6-3a9   
                           9 0 11-18 0 9   
                           9 0 0118 0z"/>  
                </svg>  
              </span>  
              <div>  
                <p class="font-semibold text-gray-800">{{ reward.name }}</p>  
                <p class="text-sm text-gray-500">  
                  Requested by <span class="font-medium">{{ reward.requested_by_username }}</span>  
                  &middot; <span class="font-medium text-yellow-700">{{ reward.points_cost }} pts</span>  
                </p>  
              </div>  
            </div>  
            <div class="flex space-x-2">  
              <a href="{{ url_for('handle_reward', reward_id=reward._id, action='approve') }}"  
                 class="p-2 text-white bg-green-500 rounded-full hover:bg-green-600  
                        transition-transform transform hover:scale-110">  
                <svg xmlns="http://www.w3.org/2000/svg"  
                     class="h-5 w-5" fill="none"  
                     viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">  
                  <path stroke-linecap="round" stroke-linejoin="round"  
                        d="M5 13l4 4L19 7"/>  
                </svg>  
              </a>  
              <a href="{{ url_for('handle_reward', reward_id=reward._id, action='reject') }}"  
                 class="p-2 text-white bg-red-500 rounded-full hover:bg-red-600  
                        transition-transform transform hover:scale-110">  
                <svg xmlns="http://www.w3.org/2000/svg"  
                     class="h-5 w-5" fill="none"  
                     viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">  
                  <path stroke-linecap="round" stroke-linejoin="round"  
                        d="M6 18L18 6M6 6l12 12"/>  
                </svg>  
              </a>  
            </div>  
          </div>  
        {% else %}  
          <p class="text-center py-8 text-gray-500">  
            No pending reward requests.  
          </p>  
        {% endfor %}  
      </div>  
    </div>  
  
    <!-- TAB 4: Spend History -->  
    <div id="spendHistory" class="tab-content">  
      <h3 class="text-2xl font-bold mb-6 text-gray-900">All Reward Spend Transactions</h3>  
      <div class="space-y-4">  
        {% if spend_history %}  
          {% for tx in spend_history %}  
          <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg  
                      flex items-center justify-between hover:shadow-md transition-shadow">  
            <div>  
              <p class="font-semibold text-gray-800">  
                {{ tx.child_username }} spent <span class="text-blue-600 font-bold">{{ tx.points_spent }} pts</span>  
                on "{{ tx.reward_name }}"  
              </p>  
              <p class="text-sm text-gray-500">  
                Status: {{ tx.status|capitalize }} &middot; {{ tx.spent_at_pretty }}  
              </p>  
            </div>  
          </div>  
          {% endfor %}  
        {% else %}  
          <p class="text-center py-8 text-gray-500">  
            No spend history recorded yet.  
          </p>  
        {% endif %}  
      </div>  
    </div>  
  </div>  
</div>  
  
<script>  
function switchTab(event, tabID) {  
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));  
  document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));  
  document.getElementById(tabID).classList.add('active');  
  event.currentTarget.classList.add('active');  
}  
</script>  
{% endblock %}  
"""  
  
DASHBOARD_CHILD_TEMPLATE = """{% block content %}  
<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">  
  <div class="lg:col-span-2 space-y-8">  
    <!-- Daily Habits -->  
    <div class="bg-white p-6 rounded-2xl shadow-xl">  
      <h2 class="text-2xl font-bold mb-4 flex items-center gap-3">  
        <svg xmlns="http://www.w3.org/2000/svg"  
             class="h-7 w-7 text-pink-500" fill="currentColor"  
             viewBox="0 0 20 20">  
          <path fill-rule="evenodd"  
                d="M3.172 5.172a4 4 0 015.656 0L10   
                   6.343l1.172-1.171a4 4 0   
                   115.656 5.656L10 17.657l-6.828  
                   -6.829a4 4 0 010-5.656z"  
                clip-rule="evenodd"/>  
        </svg>  
        My Daily Habits  
      </h2>  
      <div class="space-y-4">  
        {% set habits = events|selectattr("type","equalto","habit")|list %}  
        {% if habits %}  
          {% for habit in habits %}  
          <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg  
                      flex flex-col sm:flex-row justify-between items-start sm:items-center  
                      hover:shadow-md transition-shadow">  
            <div class="flex-1">  
              <h4 class="font-bold text-lg text-gray-800">{{ habit.name }}</h4>  
              <p class="text-sm text-gray-600 mt-1 pr-4">{{ habit.description }}</p>  
              <div class="flex items-center gap-4 mt-3 text-sm">  
                <span class="font-bold text-green-600 bg-green-100 px-2 py-0.5  
                            rounded-full">+{{ habit.points }} pts</span>  
                <span class="font-semibold text-orange-600 bg-orange-100 px-2 py-0.5  
                            rounded-full flex items-center gap-1">  
                  <svg xmlns="http://www.w3.org/2000/svg"  
                       class="h-4 w-4" fill="currentColor"  
                       viewBox="0 0 20 20">  
                    <path fill-rule="evenodd"  
                          d="M12.395 2.553a1 1 0   
                             00-1.45-.385c-.345.23  
                             -.614.558-.822.934l-6.75   
                             12.25a1 1 0   
                             001.64.905l1.852-1.069a1   
                             1 0 011.23.372l3.22   
                             4.705a1 1 0   
                             001.64-.905l-1.852  
                             -1.069a1 1 0   
                             01-.001-1.422l6.75-12.25a1  
                             1 0 00-.385-1.45z"  
                          clip-rule="evenodd"/>  
                  </svg>  
                  Streak: {{ habit.streak|default(0) }} days  
                </span>  
              </div>  
            </div>  
            <div class="mt-4 sm:mt-0 w-full sm:w-auto">  
              {% if habit.can_checkin %}  
              <a href="{{ url_for('checkin_habit', event_id=habit._id) }}"  
                 class="w-full sm:w-auto flex justify-center items-center gap-2  
                        px-5 py-2.5 text-sm font-semibold text-white bg-green-500  
                        rounded-lg hover:bg-green-600 transition-transform  
                        transform hover:scale-105 shadow-md">  
                Check-in Today  
              </a>  
              {% else %}  
              <span class="flex items-center justify-center gap-2  
                          w-full sm:w-auto px-5 py-2.5 text-sm font-semibold  
                          text-green-800 bg-green-100 rounded-lg">  
                <svg xmlns="http://www.w3.org/2000/svg"  
                     class="h-5 w-5" viewBox="0 0 20 20"  
                     fill="currentColor">  
                  <path fill-rule="evenodd"  
                        d="M10 18a8 8 0   
                           100-16 8 8 0   
                           000 16zm3.707-9.293a1 1 0  
                           00-1.414-1.414L9   
                           10.586 7.707 9.293a1 1 0  
                           00-1.414 1.414l2   
                           2a1 1 0 001.414 0l4-4z"  
                        clip-rule="evenodd"/>  
                </svg>  
                Completed Today!  
              </span>  
              {% endif %}  
            </div>  
          </div>  
          {% endfor %}  
        {% else %}  
          <p class="text-center py-6 text-gray-500">  
            You have no habits assigned yet.  
          </p>  
        {% endif %}  
      </div>  
    </div>  
  
    <!-- Assigned Chores -->  
    <div class="bg-white p-6 rounded-2xl shadow-xl">  
      <h2 class="text-2xl font-bold mb-4 flex items-center gap-3">  
        <svg xmlns="http://www.w3.org/2000/svg"  
             class="h-7 w-7 text-purple-500" viewBox="0 0 20 20"  
             fill="currentColor">  
          <path d="M5 3a2 2 0   
                   00-2 2v2a2 2 0   
                   002 2h2a2 2 0   
                   002-2V5a2 2 0  
                   00-2-2H5zM5 11a2 2 0  
                   00-2 2v2a2 2 0   
                   002 2h2a2 2  
                   0 002-2v-2a2 2   
                   0 00-2-2H5zM11 5a2 2   
                   0 012-2h2a2 2 0   
                   012 2v2a2 2  
                   0 01-2 2h-2a2 2   
                   0 01-2-2V5zM11 13a2 2   
                   0 012-2h2a2 2   
                   0 012 2v2a2 2   
                   0 01-2 2h-2a2 2  
                   0 01-2-2v-2z"/>  
        </svg>  
        My Assigned Chores  
      </h2>  
      <div class="space-y-4">  
        {% set chores = events|selectattr("type","equalto","chore")|list %}  
        {% if chores %}  
          {% for chore in chores %}  
          <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg  
                      flex flex-col sm:flex-row justify-between items-start sm:items-center  
                      hover:shadow-md transition-shadow">  
            <div class="flex-1">  
              <h4 class="font-bold text-lg text-gray-800">{{ chore.name }}</h4>  
              <p class="text-sm text-gray-600 mt-1 pr-4">{{ chore.description }}</p>  
              <div class="flex items-center gap-4 mt-3 text-sm">  
                <span class="font-bold text-purple-600 bg-purple-100 px-2 py-0.5  
                            rounded-full">+{{ chore.points }} pts</span>  
                <span class="font-semibold text-gray-600 flex items-center gap-1.5">  
                  <svg xmlns="http://www.w3.org/2000/svg"  
                       class="h-4 w-4" fill="currentColor"  
                       viewBox="0 0 20 20">  
                    <path fill-rule="evenodd"  
                          d="M6 2a1 1 0   
                             00-1 1v1H4a2 2 0   
                             00-2 2v10a2 2 0   
                             002 2h12a2 2 0   
                             002-2V6a2 2 0   
                             00-2-2h-1V3a1   
                             1 0 10-2 0v1H7V3a1  
                             1 0 00-1-1zm0   
                             5a1 1 0 000 2h8a1   
                             1 0 100-2H6z"  
                          clip-rule="evenodd"/>  
                  </svg>  
                  Due: {{ chore.due_date.strftime('%b %d, %Y') }}  
                </span>  
              </div>  
            </div>  
            <div class="mt-4 sm:mt-0 w-full sm:w-auto">  
              {% if chore.status == 'assigned' %}  
                <a href="{{ url_for('complete_event', event_id=chore._id) }}"  
                   class="w-full sm:w-auto flex justify-center items-center  
                          gap-2 px-5 py-2.5 text-sm font-semibold text-white  
                          bg-blue-500 rounded-lg hover:bg-blue-600  
                          transition-transform transform hover:scale-105 shadow-md">  
                  Mark as Done  
                </a>  
              {% elif chore.status == 'completed' %}  
                <span class="flex items-center justify-center gap-2 w-full sm:w-auto  
                            px-5 py-2.5 text-sm font-semibold text-indigo-800 bg-indigo-100 rounded-lg">  
                  Awaiting Approval  
                </span>  
              {% elif chore.status == 'approved' %}  
                <span class="flex items-center justify-center gap-2 w-full sm:w-auto  
                            px-5 py-2.5 text-sm font-semibold text-green-800 bg-green-100 rounded-lg">  
                  Approved!  
                </span>  
              {% endif %}  
            </div>  
          </div>  
          {% endfor %}  
        {% else %}  
          <p class="text-center py-6 text-gray-500">  
            You have no chores assigned. Great job!  
          </p>  
        {% endif %}  
      </div>  
    </div>  
  </div>  
  
  <!-- Right column: Points + Rewards -->  
  <div class="lg:col-span-1 space-y-8">  
    <!-- Points + Lifetime Points -->  
    <div class="bg-gradient-to-br from-blue-500 to-indigo-600 text-white p-6  
                rounded-2xl shadow-xl text-center">  
      <p class="text-lg font-medium opacity-80">My Available Points</p>  
      <p class="text-6xl font-extrabold my-2 tracking-tight">  
        {{ current_user.points }}  
      </p>  
      <p class="opacity-80">  
        Lifetime Earned: {{ current_user.lifetime_points }}  
      </p>  
    </div>  
  
    <!-- Reward Request Form -->  
    <div class="bg-white p-6 rounded-2xl shadow-xl">  
      <h3 class="text-xl font-bold mb-4">Request a Reward</h3>  
      <form method="POST" action="{{ url_for('request_reward') }}" class="space-y-4">  
        <div>  
          <label for="name" class="block text-sm font-medium text-gray-700">  
            Reward  
          </label>  
          <input type="text" name="name" required placeholder="e.g., 1 hour of TV"  
                 class="mt-1 block w-full px-4 py-2.5 bg-gray-50 border-gray-300  
                        rounded-lg focus:ring-blue-500 focus:border-blue-500"/>  
        </div>  
        <div>  
          <label for="points_cost" class="block text-sm font-medium text-gray-700">  
            Points Cost  
          </label>  
          <input type="number" name="points_cost" min="1" required placeholder="e.g. 100"  
                 class="mt-1 block w-full px-4 py-2.5 bg-gray-50 border-gray-300  
                        rounded-lg focus:ring-blue-500 focus:border-blue-500"/>  
        </div>  
        <button type="submit"  
                class="w-full py-2.5 px-4 font-semibold text-white bg-secondary-500  
                       rounded-lg hover:bg-secondary-600 transition-transform  
                       transform hover:scale-105 shadow-md">  
          Request Reward  
        </button>  
      </form>  
      <hr class="my-6">  
      <h3 class="text-xl font-bold mb-4">Reward History</h3>  
      <div class="space-y-3 max-h-60 overflow-y-auto custom-scrollbar pr-2">  
        {% for reward in rewards|sort(attribute='_id', reverse=true) %}  
          <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">  
            <div>  
              <p class="text-sm font-semibold pr-2">  
                {{ reward.name }} ({{ reward.points_cost }} pts)  
              </p>  
              {% if reward.status in ['approved','rejected'] and reward.resolved_at %}  
                {% set delta = now - reward.resolved_at %}  
                <p class="text-xs text-gray-500">  
                  {% if delta.days > 0 %}  
                    Resolved {{ delta.days }}d ago  
                  {% elif delta.seconds > 3600 %}  
                    Resolved {{ delta.seconds // 3600 }}h ago  
                  {% else %}  
                    Resolved {{ max(1, delta.seconds // 60) }}m ago  
                  {% endif %}  
                </p>  
              {% endif %}  
            </div>  
            <span class="flex-shrink-0 px-2.5 py-0.5 text-xs font-medium rounded-full  
                  {{ {'requested':'bg-yellow-100 text-yellow-800',  
                      'approved':'bg-green-100 text-green-800',  
                      'rejected':'bg-red-100 text-red-800'}[reward.status] }}">  
              {{ reward.status|capitalize }}  
            </span>  
          </div>  
        {% else %}  
          <p class="text-sm text-center py-4 text-gray-500">  
            You haven't requested any rewards yet.  
          </p>  
        {% endfor %}  
      </div>  
    </div>  
  </div>  
</div>  
{% endblock %}  
"""  
  
INVITE_TEMPLATE = """{% block content %}  
<div class="bg-white p-8 sm:p-12 rounded-2xl shadow-xl text-center max-w-lg mx-auto">  
  <div class="mx-auto bg-blue-100 h-16 w-16 rounded-full flex items-center justify-center">  
    <svg xmlns="http://www.w3.org/2000/svg"  
         class="h-8 w-8 text-blue-600" fill="none"  
         viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">  
      <path stroke-linecap="round" stroke-linejoin="round"  
            d="M17 20h5v-2a3 3 0  
               00-5.356-1.857M17 20H7m10  
               0v-2c0-.656-.126-1.283-.356  
               -1.857M7 20H2v-2a3 3 0  
               015.356-1.857M7 20v-2c0  
               -.656.126-1.283.356  
               -1.857m0 0a5.002 5.002  
               0 019.288 0M15 7a3 3  
               0 11-6 0 3 3 0 016  
               0zm6 3a2 2 0  
               11-4 0 2 2 0  
               014 0zM7 10a2 2 0  
               11-4 0 2 2 0  
               014 0z"/>  
    </svg>  
  </div>  
  <h2 class="text-3xl font-extrabold mt-4">Invite Your Family</h2>  
  <p class="text-gray-600 mt-2 mb-8">  
    Share this code or QR code so your child can join your family hub.  
  </p>  
  <div class="mb-8">  
    <label class="text-sm font-medium text-gray-700">  
      Your Unique Invite Code  
    </label>  
    <div class="text-4xl font-mono p-4 mt-2 bg-gray-100  
                rounded-lg inline-block tracking-widest  
                text-gray-800">  
      {{ invite_code }}  
    </div>  
  </div>  
  <div>  
    <label class="text-sm font-medium text-gray-700">  
      Or Scan with a Phone Camera  
    </label>  
    <img src="{{ url_for('qr_code') }}"  
         alt="Invite QR Code"  
         class="mx-auto border-4 mt-2 border-gray-200  
                p-2 rounded-lg bg-white">  
  </div>  
</div>  
{% endblock %}  
"""  
  
FAMILY_DASHBOARD_TEMPLATE = """{% block content %}  
<div class="space-y-8">  
  <!-- Stats row -->  
  <div class="grid grid-cols-1 md:grid-cols-3 gap-6">  
    <div class="bg-white p-6 rounded-2xl shadow-xl flex items-center space-x-4  
                transition-transform transform hover:-translate-y-1">  
      <div class="bg-green-100 p-4 rounded-2xl">  
        <svg class="w-8 h-8 text-green-600" fill="none"  
             stroke="currentColor" viewBox="0 0 24 24">  
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"  
                d="M9 12l2 2 4-4m6 2a9   
                   9 0 11-18 0 9 9   
                   0 0118 0z"/>  
        </svg>  
      </div>  
      <div>  
        <p class="text-sm text-gray-500">Tasks Completed This Week</p>  
        <p class="text-3xl font-bold">{{ stats.completed_this_week }}</p>  
      </div>  
    </div>  
  
    <div class="bg-white p-6 rounded-2xl shadow-xl flex items-center space-x-4  
                transition-transform transform hover:-translate-y-1">  
      <div class="bg-yellow-100 p-4 rounded-2xl">  
        <svg class="w-8 h-8 text-yellow-600" fill="none"  
             stroke="currentColor" viewBox="0 0 24 24">  
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"  
                d="M12 8v4l3 3m6-3a9   
                   9 0 11-18 0 9 9   
                   0 0118 0z"/>  
        </svg>  
      </div>  
      <div>  
        <p class="text-sm text-gray-500">Pending Approval</p>  
        <p class="text-3xl font-bold">{{ stats.pending_approval }}</p>  
      </div>  
    </div>  
  
    <div class="bg-white p-6 rounded-2xl shadow-xl flex items-center space-x-4  
                transition-transform transform hover:-translate-y-1">  
      <div class="bg-blue-100 p-4 rounded-2xl">  
        <svg xmlns="http://www.w3.org/2000/svg"  
             class="h-8 w-8 text-blue-600" fill="none"  
             viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">  
          <path stroke-linecap="round" stroke-linejoin="round"  
                d="M11.049 2.927c.3-.921  
                   1.603-.921 1.902   
                   0l1.519 4.674a1 1 0   
                   00.95.69h4.915c.969   
                   0 1.371 1.24.588   
                   1.81l-3.976 2.888a1   
                   1 0 00-.363 1.118l1.518   
                   4.674c.3.922-.755   
                   1.688-1.538 1.118l-3.976  
                   -2.888a1 1 0   
                   00-1.176 0l-3.976  
                   2.888c-.783.57  
                   -1.838-.196-1.538-1.118l  
                   1.518-4.674a1  
                   1 0 00-.363-1.118l  
                   -3.976-2.888c-.783-.57  
                   -.38-1.81.588-1.81  
                   h4.914a1 1 0  
                   00.951-.69l1.519  
                   -4.674z"/>  
        </svg>  
      </div>  
      <div>  
        <p class="text-sm text-gray-500">Total Points Awarded</p>  
        <p class="text-3xl font-bold">{{ stats.total_points_awarded }}</p>  
      </div>  
    </div>  
  </div>  
  
  <!-- Weekly Chart + Leaderboard -->  
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">  
    <div class="lg:col-span-2 bg-white p-6 rounded-2xl shadow-xl">  
      <h3 class="text-xl font-bold mb-4 text-gray-900">Weekly Task Completion</h3>  
      <div class="h-80">  
        <canvas id="weeklyCompletionChart"></canvas>  
      </div>  
    </div>  
    <div class="lg:col-span-1 bg-white p-6 rounded-2xl shadow-xl">  
      <h3 class="text-xl font-bold mb-4 text-gray-900">Family Leaderboard 🏆</h3>  
      <div class="space-y-4">  
        {% for member in family_members|sort(attribute='points', reverse=true) %}  
        <div class="flex items-center justify-between p-3 rounded-lg  
                    {{ 'bg-yellow-100' if loop.index == 1 else 'bg-gray-50' }}">  
          <div class="flex items-center space-x-3">  
            <span class="text-lg font-bold w-6 text-center  
                        {{ 'text-yellow-600' if loop.index == 1  
                           else 'text-gray-400' }}">  
              {{ loop.index }}  
            </span>  
            <div class="w-8 h-8 rounded-full bg-blue-200 flex  
                        items-center justify-center font-bold text-blue-700">  
              {{ member.username[0]|upper }}  
            </div>  
            <span class="font-medium">{{ member.username }}</span>  
          </div>  
          <span class="font-bold text-blue-600">{{ member.points }} pts</span>  
        </div>  
        {% else %}  
        <p class="text-center text-gray-500 py-6">  
          Invite family members to start the leaderboard!  
        </p>  
        {% endfor %}  
      </div>  
    </div>  
  </div>  
  
  <!-- Recent Activity -->  
  <div class="bg-white p-6 rounded-2xl shadow-xl">  
    <h3 class="text-xl font-bold mb-4 text-gray-900">Recent Activity</h3>  
    <div class="space-y-3 max-h-72 overflow-y-auto custom-scrollbar pr-2">  
      {% for event in recent_events %}  
      <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">  
        <div class="flex items-center gap-3">  
          <span class="text-green-500">  
            <svg xmlns="http://www.w3.org/2000/svg"  
                 class="h-5 w-5" fill="currentColor"  
                 viewBox="0 0 20 20">  
              <path fill-rule="evenodd"  
                    d="M10 18a8 8 0  
                       100-16 8 8 0  
                       000 16zm3.707-9.293a1  
                       1 0 00-1.414-1.414L9  
                       10.586 7.707 9.293a1  
                       1 0 00-1.414 1.414l2  
                       2a1 1 0 001.414 0l4-4z"  
                    clip-rule="evenodd"/>  
            </svg>  
          </span>  
          <p>  
            <span class="font-semibold">{{ event.assigned_to_username }}</span>  
            earned <span class="font-semibold text-green-700">{{ event.points }} points</span>   
            for completing <span class="font-semibold">{{ event.name }}</span>.  
          </p>  
        </div>  
        <p class="text-sm text-gray-500 whitespace-nowrap">  
          {{ event.approved_at_pretty }}  
        </p>  
      </div>  
      {% else %}  
      <p class="text-center text-gray-500 py-6">  
        No tasks have been approved yet.  
      </p>  
      {% endfor %}  
    </div>  
  </div>  
</div>  
  
<script>  
document.addEventListener('DOMContentLoaded', function() {  
  const weeklyCtx = document.getElementById('weeklyCompletionChart').getContext('2d');  
  const weeklyData = {{ stats.weekly_completion_data | tojson }};  
  const gradient = weeklyCtx.createLinearGradient(0, 0, 0, 300);  
  gradient.addColorStop(0, 'rgba(59, 130, 246, 0.5)');  
  gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');  
  
  new Chart(weeklyCtx, {  
    type: 'line',  
    data: {  
      labels: weeklyData.labels,  
      datasets: [{  
        label: 'Tasks Completed',  
        data: weeklyData.data,  
        backgroundColor: gradient,  
        borderColor: '#3b82f6',  
        borderWidth: 2,  
        pointBackgroundColor: '#3b82f6',  
        pointRadius: 4,  
        tension: 0.4,  
        fill: true,  
      }]  
    },  
    options: {  
      responsive: true,  
      maintainAspectRatio: false,  
      scales: {  
        y: {  
          beginAtZero: true,  
          ticks: { precision: 0 },  
          grid: { drawBorder: false }  
        },  
        x: { grid: { display: false } }  
      },  
      plugins: { legend: { display: false } }  
    }  
  });  
});  
</script>  
{% endblock %}  
"""  
  
CALENDAR_FOCUS_TEMPLATE = """{% block content %}  
<div id="eventModal" class="fixed inset-0 bg-gray-900 bg-opacity-60 overflow-y-auto  
                          h-full w-full z-50 hidden flex items-center justify-center">  
  <div class="relative p-6 border w-full max-w-lg shadow-2xl  
              rounded-2xl bg-white modal-content mx-4">  
    <button id="closeModal"  
            class="absolute top-4 right-4 text-gray-400 hover:text-gray-600 text-3xl">  
      &times;  
    </button>  
    <div class="flex items-center gap-4 pb-4 border-b">  
      <div id="modal-icon"  
           class="w-12 h-12 rounded-lg flex items-center justify-center"></div>  
      <div>  
        <h3 id="modal-title" class="text-2xl font-bold"></h3>  
        <div id="modal-assignee" class="text-sm text-gray-600"></div>  
      </div>  
    </div>  
    <div class="mt-4">  
      <p class="text-gray-700" id="modal-description"></p>  
      <div class="flex items-center justify-between mt-6 p-4 bg-gray-50 rounded-lg">  
        <div class="flex items-center gap-2">  
          <span id="modal-status-badge"></span>  
        </div>  
        <div class="text-lg font-bold text-green-600 bg-green-100 px-3 py-1 rounded-full">  
          <span id="modal-points"></span> pts  
        </div>  
      </div>  
    </div>  
  </div>  
</div>  
  
<div class="bg-white p-4 sm:p-6 rounded-2xl shadow-xl">  
  <div class="md:flex justify-between items-center mb-6">  
    <h2 class="text-2xl font-bold mb-4 md:mb-0 text-gray-900">Family Calendar</h2>  
    <div class="grid grid-cols-1 sm:grid-cols-2 md:flex items-center gap-4">  
      <input type="text" id="filter-search" placeholder="Search by name..."  
             class="w-full md:w-auto px-3 py-2 bg-gray-50 border border-gray-300  
                    rounded-lg shadow-sm focus:outline-none  
                    focus:ring-blue-500 focus:border-blue-500">  
      <select id="filter-member"  
              class="w-full md:w-auto px-3 py-2 bg-gray-50 border border-gray-300  
                     rounded-lg shadow-sm">  
        <option value="">All Members</option>  
        {% for member in family_members if member.role == 'child' %}  
          <option value="{{ member._id }}">{{ member.username }}</option>  
        {% endfor %}  
      </select>  
      <select id="filter-type"  
              class="w-full md:w-auto px-3 py-2 bg-gray-50 border border-gray-300  
                     rounded-lg shadow-sm">  
        <option value="">All Types</option>  
        <option value="chore">Chores</option>  
        <option value="habit">Habits</option>  
      </select>  
      <button id="apply-filters"  
              class="w-full sm:col-span-2 md:w-auto px-4 py-2 font-semibold  
                     text-white bg-blue-600 rounded-lg hover:bg-blue-700">  
        Apply Filters  
      </button>  
    </div>  
  </div>  
  <div id='calendar' class="text-sm md:text-base"></div>  
</div>  
  
<script>  
document.addEventListener('DOMContentLoaded', function() {  
  const modal = document.getElementById('eventModal');  
  const closeModalBtn = document.getElementById('closeModal');  
  const applyFiltersBtn = document.getElementById('apply-filters');  
  const calendarEl = document.getElementById('calendar');  
  
  closeModalBtn.onclick = () => modal.classList.add('hidden');  
  window.onclick = (e) => { if(e.target == modal) modal.classList.add('hidden'); };  
  
  const getEventSourceUrl = () => {  
    const params = new URLSearchParams({  
      search: document.getElementById('filter-search').value,  
      member: document.getElementById('filter-member').value,  
      type: document.getElementById('filter-type').value  
    });  
    return `/api/events?${params.toString()}`;  
  };  
  
  const calendar = new FullCalendar.Calendar(calendarEl, {  
    initialView: 'dayGridMonth',  
    headerToolbar: {  
      left: 'prev,next today',  
      center: 'title',  
      right: 'dayGridMonth,timeGridWeek,listWeek'  
    },  
    events: getEventSourceUrl(),  
    eventClick: function(info) {  
      const eProps = info.event.extendedProps;  
      document.getElementById('modal-title').innerText = info.event.title;  
      document.getElementById('modal-description').innerText =  
          eProps.description || 'No description provided.';  
      document.getElementById('modal-points').innerText = eProps.points;  
      document.getElementById('modal-assignee').innerHTML =  
        '<span class="font-semibold">Assigned to:</span> ' + eProps.assignee_name;  
  
      const statusColors = {  
        'assigned': 'bg-yellow-100 text-yellow-800',  
        'completed': 'bg-indigo-100 text-indigo-800',  
        'approved':  'bg-green-100 text-green-800'  
      };  
      const sText = eProps.status.charAt(0).toUpperCase() + eProps.status.slice(1);  
      document.getElementById('modal-status-badge').innerHTML =  
        `<span class="px-3 py-1 text-sm font-medium rounded-full ${  
          statusColors[eProps.status] || 'bg-gray-100'  
        }">${sText}</span>`;  
  
      const icon = document.getElementById('modal-icon');  
      if(eProps.type === 'habit') {  
        icon.className = 'w-12 h-12 rounded-lg flex items-center justify-center bg-pink-100';  
        icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7 text-pink-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" /></svg>';  
      } else {  
        icon.className = 'w-12 h-12 rounded-lg flex items-center justify-center bg-purple-100';  
        icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" /></svg>';  
      }  
      modal.classList.remove('hidden');  
    },  
    height: 'auto',  
    eventDidMount: (info) => {  
      let iconEl = document.createElement('i');  
      iconEl.style.cssText = 'font-style: normal; margin-right: 5px;';  
      iconEl.innerText = info.event.extendedProps.type === 'habit' ? '💖' : '⭐';  
      info.el.querySelector('.fc-event-title').prepend(iconEl);  
    }  
  });  
  calendar.render();  
  
  applyFiltersBtn.addEventListener('click', () => {  
    calendar.removeAllEventSources();  
    calendar.addEventSource(getEventSourceUrl());  
  });  
});  
</script>  
{% endblock %}  
"""  
  
# --- Flask Routes ---  
  
@app.route('/')  
def index():  
    if current_user.is_authenticated:  
        return redirect(url_for('family_dashboard'))  
    return redirect(url_for('login'))  
  
@app.route('/dashboard')  
@login_required  
def personal_dashboard():  
    """  
    Shows either parent's or child's perspective on tasks & rewards.  
    """  
    if current_user.role == 'parent':  
        # Gather data for parent's multi-tab dashboard  
        family_members = list(users_collection.find({'family_id': current_user.family_id}))  
        member_map = {str(m['_id']): m['username'] for m in family_members}  
  
        # Pending or completed tasks  
        events = list(events_collection.find({  
            'family_id': current_user.family_id,  
            'status': {'$in': ['completed', 'approved']}  
        }).sort('due_date', DESCENDING).limit(20))  
  
        # Reward requests  
        reward_requests_cursor = rewards_collection.find({  
            'family_id': current_user.family_id,  
            'status': 'requested'  
        }).sort('_id', -1)  
        reward_requests = []  
        for r in reward_requests_cursor:  
            r['requested_by_username'] = member_map.get(str(r.get('requested_by_id')), 'Unknown')  
            reward_requests.append(r)  
  
        # Spend History: from transactions  
        spend_tx = list(transactions_collection.find({  
            'family_id': current_user.family_id  
        }).sort('spent_at', DESCENDING))  
  
        # Format times  
        for t in spend_tx:  
            delta = datetime.utcnow() - t['spent_at']  
            if delta.days > 0:  
                t['spent_at_pretty'] = f"{delta.days}d ago"  
            elif delta.seconds > 3600:  
                t['spent_at_pretty'] = f"{delta.seconds // 3600}h ago"  
            else:  
                t['spent_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"  
  
        return render_full_template(DASHBOARD_PARENT_TEMPLATE,  
                                   family_members=family_members,  
                                   events=events,  
                                   reward_requests=reward_requests,  
                                   member_map=member_map,  
                                   spend_history=spend_tx)  
    else:  
        # Child's Dashboard  
        today = datetime.utcnow().date()  
        events_cursor = events_collection.find({  
            'assigned_to': current_user.id,  
            'status': {'$in': ['assigned','completed','approved']}  
        }).sort('due_date', ASCENDING)  
  
        child_events = []  
        for e in events_cursor:  
            if e['type'] == 'habit':  
                # can check in if not done today  
                last_check = e.get('last_completed')  
                e['can_checkin'] = not(last_check and last_check.date() == today)  
            child_events.append(e)  
  
        # Show child's rewards in the sidebar  
        now = datetime.utcnow()  
        child_rewards = list(rewards_collection.find({  
            'requested_by_id': current_user.id  
        }))  
  
        return render_full_template(DASHBOARD_CHILD_TEMPLATE,  
                                   events=child_events,  
                                   rewards=child_rewards,  
                                   now=now)  
  
@app.route('/family-dashboard')  
@login_required  
def family_dashboard():  
    """  
    Family overview: stats, leaderboard, recent activity.  
    """  
    fam_id = current_user.family_id  
    family_members = list(users_collection.find({'family_id': fam_id}))  
    member_map = {str(m['_id']): m['username'] for m in family_members}  
    events = list(events_collection.find({'family_id': fam_id}))  
    stats = {  
      "completed_this_week": 0,  
      "pending_approval": 0,  
      "total_points_awarded": sum(m.get('points',0) for m in family_members),  
      "weekly_completion_data": {"labels":[],"data":[]}  
    }  
  
    today = datetime.utcnow()  
    one_week_ago = today - timedelta(days=7)  
    day_counts = { (today - timedelta(days=i)).strftime('%a'): 0 for i in range(7) }  
  
    for e in events:  
        if e.get('status') == 'completed':  
            stats['pending_approval'] += 1  
        if e.get('status') == 'approved' and e.get('approved_at'):  
            if e['approved_at'] > one_week_ago:  
                stats['completed_this_week'] += 1  
                day_label = e['approved_at'].strftime('%a')  
                if day_label in day_counts:  
                    day_counts[day_label]+=1  
  
    stats['weekly_completion_data']['labels'] = list(day_counts.keys())[::-1]  
    stats['weekly_completion_data']['data'] = list(day_counts.values())[::-1]  
  
    # recent approved events  
    rec_cursor = events_collection.find({  
        'family_id': fam_id,  
        'status': 'approved'  
    }).sort('approved_at', DESCENDING).limit(5)  
  
    recent_events = []  
    for ev in rec_cursor:  
        ev['assigned_to_username'] = member_map.get(str(ev.get('assigned_to')), 'Unknown')  
        if ev.get('approved_at'):  
            delta = datetime.utcnow() - ev['approved_at']  
            if delta.days>0:  
                ev['approved_at_pretty'] = f"{delta.days}d ago"  
            elif delta.seconds>3600:  
                ev['approved_at_pretty'] = f"{delta.seconds // 3600}h ago"  
            else:  
                ev['approved_at_pretty'] = f"{max(1, delta.seconds // 60)}m ago"  
        else:  
            ev['approved_at_pretty'] = 'Recently'  
        recent_events.append(ev)  
  
    return render_full_template(FAMILY_DASHBOARD_TEMPLATE,  
                               stats=stats,  
                               family_members=family_members,  
                               recent_events=recent_events)  
  
@app.route('/calendar-focus')  
@login_required  
def calendar_focus():  
    """FullCalendar-based overview."""  
    family_members = list(users_collection.find({'family_id': current_user.family_id}))  
    return render_full_template(CALENDAR_FOCUS_TEMPLATE, family_members=family_members)  
  
@app.route('/login', methods=['GET','POST'])  
def login():  
    if current_user.is_authenticated:  
        return redirect(url_for('family_dashboard'))  
    if request.method == 'POST':  
        identifier = request.form['email_or_username']  
        user_data = users_collection.find_one({'$or':[{'email': identifier},{'username': identifier}]})  
        if user_data and bcrypt.check_password_hash(user_data['password_hash'], request.form['password']):  
            login_user(User(user_data))  
            return redirect(url_for('family_dashboard'))  
        else:  
            flash('Invalid credentials. Please try again.', 'error')  
    return render_full_template(LOGIN_TEMPLATE)  
  
@app.route('/logout')  
@login_required  
def logout():  
    logout_user()  
    return redirect(url_for('login'))  
  
@app.route('/register/parent', methods=['GET','POST'])  
def register_parent():  
    """A new parent registration => new family hub."""  
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
  
        # parent's _id is the family's ID  
        users_collection.update_one({'_id': new_id},  
            {'$set': {'family_id': str(new_id)}})  
  
        flash('Parent account created! Please log in.', 'success')  
        return redirect(url_for('login'))  
  
    return render_full_template(REGISTER_PARENT_TEMPLATE)  
  
@app.route('/register/child/<invite_code>', methods=['GET','POST'])  
def register_child(invite_code):  
    """Used by child to join the parent's family; code = parent's _id."""  
    try:  
        parent = users_collection.find_one({'_id': ObjectId(invite_code)})  
        if not parent or parent.get('role')!='parent':  
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
    return render_full_template(REGISTER_CHILD_TEMPLATE, invite_code=invite_code)  
  
@app.route('/invite')  
@login_required  
def invite():  
    """Parent invites child using this code or QR."""  
    if current_user.role != 'parent':  
        return redirect(url_for('family_dashboard'))  
    return render_full_template(INVITE_TEMPLATE, invite_code=current_user.id)  
  
@app.route('/qr_code')  
@login_required  
def qr_code():  
    """QR code for child registration link."""  
    if current_user.role != 'parent':  
        return Response(status=403)  
    invite_url = url_for('register_child', invite_code=current_user.id, _external=True)  
    img = qrcode.make(invite_url, border=2)  
    buf = io.BytesIO()  
    img.save(buf)  
    buf.seek(0)  
    return Response(buf, mimetype='image/png')  
  
# --- Event (Chore/Habit) Management ---  
  
@app.route('/event/create', methods=['POST'])  
@login_required  
def create_event():  
    """Parent creates a chore or habit."""  
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
    """Child marking a chore complete => pending approval."""  
    if current_user.role == 'child':  
        events_collection.update_one(  
            {'_id': ObjectId(event_id),  
             'assigned_to': current_user.id,  
             'type': 'chore'},  
            {'$set': {'status': 'completed'}}  
        )  
        flash('Chore marked as complete! Awaiting approval.', 'success')  
    return redirect(url_for('personal_dashboard'))  
  
@app.route('/event/habit/checkin/<event_id>')  
@login_required  
def checkin_habit(event_id):  
    """Child checks in daily => earn points + lifetime_points."""  
    if current_user.role == 'child':  
        habit = events_collection.find_one({  
            '_id': ObjectId(event_id),  
            'assigned_to': current_user.id  
        })  
        if not habit:  
            return redirect(url_for('personal_dashboard'))  
  
        today = datetime.utcnow().date()  
        yesterday = today - timedelta(days=1)  
        last_completed = habit.get('last_completed')  
        curr_streak = habit.get('streak', 0)  
  
        if last_completed and last_completed.date() == today:  
            flash('You have already checked in for this habit today.', 'error')  
            return redirect(url_for('personal_dashboard'))  
  
        # Update streak  
        new_streak = curr_streak+1 if (last_completed and last_completed.date()==yesterday) else 1  
  
        # Save updates  
        events_collection.update_one(  
            {'_id': ObjectId(event_id)},  
            {'$set': {  
                'last_completed': datetime.utcnow(),  
                'streak': new_streak  
            }}  
        )  
  
        # Increase child's points + lifetime_points  
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
    """Parent approving child's chore => awarding points + lifetime_points."""  
    if current_user.role == 'parent':  
        e = events_collection.find_one_and_update(  
            {'_id': ObjectId(event_id), 'family_id': current_user.family_id},  
            {'$set': {'status': 'approved', 'approved_at': datetime.utcnow()}}  
        )  
        if e and e.get('assigned_to'):  
            # Add points + lifetime_points for child  
            users_collection.update_one(  
                {'_id': ObjectId(e['assigned_to'])},  
                {'$inc': {  
                    'points': e['points'],  
                    'lifetime_points': e['points']  
                }}  
            )  
            flash(f"Task approved! {e['points']} points awarded.", 'success')  
    return redirect(url_for('personal_dashboard'))  
  
# --- Reward System (Child-Spending) ---  
  
@app.route('/reward/request', methods=['POST'])  
@login_required  
def request_reward():  
    """  
    Child route:  
    1) Check if child has enough points to spend  
    2) Immediately deduct points from child (spend)  
    3) Create pending reward doc  
    4) Insert a spend transaction with status 'pending'  
    If parent's later rejects => child is refunded  
    """  
    if current_user.role == 'child':  
        cost = int(request.form['points_cost'])  
        user = users_collection.find_one({'_id': ObjectId(current_user.id)})  
  
        if user.get('points', 0) < cost:  
            flash("You don't have enough available points for that reward!", 'error')  
            return redirect(url_for('personal_dashboard'))  
  
        # Deduct points immediately  
        users_collection.update_one(  
            {'_id': ObjectId(current_user.id)},  
            {'$inc': {'points': -cost}}  
        )  
  
        # Create reward doc in "requested" status  
        reward_id = rewards_collection.insert_one({  
            'name': request.form['name'],  
            'points_cost': cost,  
            'family_id': current_user.family_id,  
            'requested_by_id': current_user.id,  
            'status': 'requested',  
            'resolved_at': None   # set if approve/reject  
        }).inserted_id  
  
        # Insert transaction doc with status 'pending'  
        transactions_collection.insert_one({  
            'reward_id': reward_id,  
            'family_id': current_user.family_id,  
            'child_id': current_user.id,  
            'child_username': current_user.username,  
            'reward_name': request.form['name'],  
            'points_spent': cost,  
            'status': 'pending',  
            'spent_at': datetime.utcnow()  
        })  
  
        flash('Reward requested! Points have been deducted; waiting on parent approval.', 'success')  
    return redirect(url_for('personal_dashboard'))  
  
@app.route('/reward/handle/<reward_id>/<action>')  
@login_required  
def handle_reward(reward_id, action):  
    """  
    Parent route: Approve or reject child's reward request  
    If reject => refund child's points  
    If approve => confirm transaction  
    """  
    if current_user.role == 'parent':  
        reward = rewards_collection.find_one({  
            '_id': ObjectId(reward_id),  
            'family_id': current_user.family_id  
        })  
        if not reward:  
            flash("Reward not found.", 'error')  
            return redirect(url_for('personal_dashboard'))  
  
        tx = transactions_collection.find_one({'reward_id': reward['_id']})  
        if not tx:  
            flash("Transaction not found for this reward.", 'error')  
            return redirect(url_for('personal_dashboard'))  
  
        # Find the child  
        child = users_collection.find_one({'_id': ObjectId(reward['requested_by_id'])})  
        if not child:  
            flash("Child account not found.", 'error')  
            return redirect(url_for('personal_dashboard'))  
  
        if action == 'approve':  
            # Mark reward + transaction as 'approved'  
            rewards_collection.update_one(  
                {'_id': reward['_id']},  
                {'$set': {  
                  'status': 'approved',  
                  'resolved_at': datetime.utcnow()  
                }}  
            )  
            transactions_collection.update_one(  
                {'_id': tx['_id']},  
                {'$set': {  
                  'status': 'approved',  
                  'resolved_at': datetime.utcnow()  
                }}  
            )  
            flash("Reward approved! Points remain deducted.", 'success')  
  
        elif action == 'reject':  
            # Refund child's points  
            users_collection.update_one(  
                {'_id': child['_id']},  
                {'$inc': {'points': reward['points_cost']}}  
            )  
            # Mark reward + transaction as 'rejected'  
            rewards_collection.update_one(  
                {'_id': reward['_id']},  
                {'$set': {  
                  'status': 'rejected',  
                  'resolved_at': datetime.utcnow()  
                }}  
            )  
            transactions_collection.update_one(  
                {'_id': tx['_id']},  
                {'$set': {  
                  'status': 'rejected',  
                  'resolved_at': datetime.utcnow()  
                }}  
            )  
            flash("Reward rejected. Child's points were refunded.", 'success')  
  
    return redirect(url_for('personal_dashboard'))  
  
# --- FullCalendar API ---  
@app.route('/api/events')  
@login_required  
def api_events():  
    """JSON data used by /calendar-focus."""  
    fam_id = current_user.family_id  
    fam_members = list(users_collection.find({'family_id': fam_id}))  
    member_map = {str(m['_id']): m['username'] for m in fam_members}  
  
    query = {'family_id': fam_id}  
    if (search:=request.args.get('search')):  
        query['name'] = regex.Regex(search, 'i')  
    if (member_id:=request.args.get('member')):  
        query['assigned_to'] = member_id  
    if (etype:=request.args.get('type')):  
        query['type'] = etype  
  
    cursor = events_collection.find(query)  
    type_colors = {'chore': '#a855f7', 'habit': '#ec4899'}  
    calendar_events = []  
  
    for e in cursor:  
        calendar_events.append({  
          'title': e['name'],  
          'start': e['due_date'].isoformat(),  
          'allDay': True,  
          'color': type_colors.get(e['type'],'#6b7280'),  
          'extendedProps': {  
            'type': e.get('type'),  
            'description': e.get('description','No description.'),  
            'points': e.get('points'),  
            'status': e.get('status'),  
            'assignee_name': member_map.get(e.get('assigned_to'), 'N/A')  
          }  
        })  
    return jsonify(calendar_events)  
  
# --- Run App ---  
if __name__ == '__main__':  
    # For local dev  
    app.run(debug=True, port=5001)  
"""
 gunicorn --workers 3 --bind 0.0.0.0:$PORT app:app
  gunicorn --workers 3 --bind 0.0.0.0:5001 app:app
"""