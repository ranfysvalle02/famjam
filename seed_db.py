#!/usr/bin/env python
import os
import random
import itertools
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from bson.objectid import ObjectId
from dotenv import load_dotenv
import pytz  # Import timezone library

load_dotenv()

###############################################################################
# Configuration
###############################################################################
class DummyApp:
    """A minimal 'app' class for Flask-Bcrypt initialization."""
    config = {}

bcrypt = Bcrypt(DummyApp())

MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
DB_NAME = 'mchores_app' # Directly specified for clarity
NUM_DAYS_HISTORY = 45

# --- TIMEZONE CONFIGURATION (Matches your app.py) ---
TIMEZONE_NAME = 'America/New_York'
TIMEZONE = pytz.timezone(TIMEZONE_NAME)

def now_est():
    """Returns the current time localized to America/New_York (EST/EDT)."""
    return datetime.now(TIMEZONE)

def start_of_day_est(dt_date):
    """Returns a timezone-aware datetime representing midnight EST for the given date object."""
    dt_naive = datetime.combine(dt_date, datetime.min.time())
    return TIMEZONE.localize(dt_naive)

MOOD_CONFIG = {
    'moods': [
        {'emoji': '😡', 'desc': 'Upset', 'score': 1, 'notes': ["Felt overwhelmed today.", "Had a disagreement."]},
        {'emoji': '😟', 'desc': 'Not Happy', 'score': 2, 'notes': ["A bit tired and bored.", "Missing my friends."]},
        {'emoji': '😐', 'desc': 'Calm / Okay', 'score': 3, 'notes': ["Just a normal day.", "Feeling pretty good."]},
        {'emoji': '😄', 'desc': 'Very Happy', 'score': 4, 'notes': ["Had a great time with family!", "Finished a cool project."]}
    ]
}

###############################################################################
# Connect to MongoDB
###############################################################################
try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    # Collections
    collections = {
        name: db[name] for name in [
            'users', 'events', 'rewards', 'transactions', 'moods', 'famjam_plans',
            'timers', 'challenges', 'notes', 'personal_todos', 'direct_messages', 'families'
        ]
    }
    client.server_info()
    print(f"✅ MongoDB connection successful to '{MONGO_URI}', using database '{DB_NAME}'.\n")
except Exception as e:
    print(f"❌ Error connecting to MongoDB: {e}")
    exit()

###############################################################################
# Helper Functions
###############################################################################
def clear_collections():
    """Clears all relevant collections for a fresh start."""
    print("🗑️  Clearing existing data from all collections...")
    for name, collection in collections.items():
        collection.delete_many({})
    print("✨ Collections cleared.")

def create_family_members():
    """Creates two parents and two children linked to one Family document."""
    print("\n--- 👨‍👩‍👧‍👦 Creating Family Members (2 Parents, 2 Children) ---")

    # 1. Create Family document
    family_doc_template = {'name': "The Awesome Family", 'parent_ids': [], 'created_at': now_est()}
    family_id_obj = collections['families'].insert_one(family_doc_template).inserted_id
    family_id_str = str(family_id_obj)

    # 2. Insert Parent Users
    parent_ids, parent_docs = [], [
        {"email": "dad@example.com", "username": "Dad", "password": "password123"},
        {"email": "mom@example.com", "username": "Mom", "password": "password123"}
    ]
    for parent_info in parent_docs:
        hashed_password = bcrypt.generate_password_hash(parent_info["password"]).decode('utf-8')
        parent_id_obj = collections['users'].insert_one({
            'email': parent_info["email"], 'username': parent_info["username"],
            'password_hash': hashed_password, 'role': 'parent', 'family_id': family_id_str,
            'points': 0, 'lifetime_points': 0
        }).inserted_id
        parent_ids.append(str(parent_id_obj))
        print(f"👤 Parent created -> username: {parent_info['username']}")

    collections['families'].update_one({'_id': family_id_obj}, {'$set': {'parent_ids': [ObjectId(pid) for pid in parent_ids]}})
    print(f"🏡 Family document updated with ID: {family_id_str}")

    # 3. Insert Child Users
    child_ids, child_docs = [], [
        {"username": "Leo", "password": "password123", "points": 120, "lifetime": 350},
        {"username": "Mia", "password": "password123", "points": 250, "lifetime": 580}
    ]
    for child_info in child_docs:
        child_hash = bcrypt.generate_password_hash(child_info["password"]).decode('utf-8')
        child_id_obj = collections['users'].insert_one({
            'username': child_info["username"], 'password_hash': child_hash,
            'role': 'child', 'family_id': family_id_str, 'points': child_info["points"],
            'lifetime_points': child_info["lifetime"]
        }).inserted_id
        child_ids.append(str(child_id_obj))
        print(f"👤 Child created -> username: {child_info['username']}")

    return family_id_str, parent_ids, child_ids

def create_events_and_history(family_id, child_ids):
    """Generates a rich history of events: overdue, today, upcoming, and approved."""
    print("\n--- 🗓️  Generating Chore & Habit History ---")
    family_oid = ObjectId(family_id)
    today = now_est().date()
    today_dt = start_of_day_est(today)
    yesterday_dt = start_of_day_est(today - timedelta(days=1))
    
    events_to_insert = []
    leo_id, mia_id = child_ids[0], child_ids[1]

    # --- 1. OVERDUE Chores ---
    events_to_insert.append({
        'name': "Put Away Laundry", 'description': "Fold and put away all clean clothes from the basket.",
        'points': 25, 'type': 'chore', 'family_id': family_oid, 'assigned_to': leo_id,
        'status': 'assigned', 'due_date': today_dt - timedelta(days=2), 'source_type': 'manual'
    })

    # --- 2. TODAY'S Chores & Habits ---
    # Leo: Chore to do + Habit with active streak
    events_to_insert.extend([
        {
            'name': "Feed the Dog", 'description': "Morning and evening feeding.", 'points': 10,
            'type': 'chore', 'family_id': family_oid, 'assigned_to': leo_id, 'status': 'assigned',
            'due_date': today_dt, 'source_type': 'manual'
        },
        {
            'name': "Practice Instrument", 'description': "Complete a 15-minute practice session.", 'points': 15,
            'type': 'habit', 'family_id': family_oid, 'assigned_to': leo_id, 'status': 'assigned',
            'due_date': today_dt, 'streak': 12, 'last_completed': yesterday_dt
        }
    ])
    # Mia: Chore already completed + Habit with a broken streak
    events_to_insert.extend([
        {
            'name': "Tidy Your Bedroom", 'description': "Make bed, put away clothes/toys.", 'points': 20,
            'type': 'chore', 'family_id': family_oid, 'assigned_to': mia_id, 'status': 'completed',
            'due_date': today_dt, 'completed_at': now_est() - timedelta(hours=1), 'source_type': 'manual'
        },
        {
            'name': "Read for 20 Minutes", 'description': "Read a book, not a screen!", 'points': 20,
            'type': 'habit', 'family_id': family_oid, 'assigned_to': mia_id, 'status': 'assigned',
            'due_date': today_dt, 'streak': 0, 'last_completed': today_dt - timedelta(days=4)
        }
    ])

    # --- 3. UPCOMING Chores ---
    events_to_insert.append({
        'name': "Weekly Bathroom Clean", 'description': "Wipe sink, mirror, and toilet.", 'points': 40,
        'type': 'chore', 'family_id': family_oid, 'assigned_to': mia_id, 'status': 'assigned',
        'due_date': today_dt + timedelta(days=3), 'source_type': 'manual'
    })

    # --- 4. HISTORICAL Approved Chores (for charts) ---
    for i in range(1, NUM_DAYS_HISTORY):
        chore_date = today_dt - timedelta(days=i)
        if random.random() < 0.8: # Don't create chores for every single past day
            events_to_insert.append({
                'name': random.choice(["Unload Dishwasher", "Take Out Trash", "Water Plants"]),
                'points': random.randint(10, 30), 'type': 'chore', 'family_id': family_oid,
                'assigned_to': random.choice(child_ids), 'status': 'approved', 'due_date': chore_date,
                'approved_at': chore_date + timedelta(hours=random.randint(5, 28))
            })

    if events_to_insert:
        collections['events'].insert_many(events_to_insert)
        print(f"✅ Inserted {len(events_to_insert)} strategic and historical event records.")


def create_rewards_and_transactions(family_id, child_ids_map):
    """Generates a history of reward requests, with one pending."""
    print("\n--- 🎁 Generating Rewards & Transactions ---")
    family_oid = ObjectId(family_id)
    rewards_to_insert, transactions_to_insert = [], []

    # One pending request for the parent dashboard
    reward_id_pending = ObjectId()
    rewards_to_insert.append({
        '_id': reward_id_pending, 'name': 'One Hour of Video Games', 'points_cost': 100,
        'family_id': family_oid, 'requested_by_id': list(child_ids_map.keys())[0],
        'status': 'requested', 'resolved_at': None
    })
    transactions_to_insert.append({
        'reward_id': reward_id_pending, 'family_id': family_oid, 'child_id': list(child_ids_map.keys())[0],
        'child_username': list(child_ids_map.values())[0], 'reward_name': 'One Hour of Video Games',
        'points_spent': 100, 'status': 'pending', 'spent_at': now_est() - timedelta(hours=3)
    })

    # Several historical approved/rejected requests
    for _ in range(5):
        reward_id = ObjectId()
        child_id, child_name = random.choice(list(child_ids_map.items()))
        status = random.choices(['approved', 'rejected'], weights=[0.8, 0.2], k=1)[0]
        spent_at = now_est() - timedelta(days=random.randint(2, NUM_DAYS_HISTORY))
        resolved_at = spent_at + timedelta(hours=random.randint(4, 24))
        rewards_to_insert.append({
            '_id': reward_id, 'name': 'Movie Night Choice', 'points_cost': 150, 'family_id': family_oid,
            'requested_by_id': child_id, 'status': status, 'resolved_at': resolved_at
        })
        transactions_to_insert.append({
            'reward_id': reward_id, 'family_id': family_oid, 'child_id': child_id, 'child_username': child_name,
            'reward_name': 'Movie Night Choice', 'points_spent': 150, 'status': status,
            'spent_at': spent_at, 'resolved_at': resolved_at
        })

    collections['rewards'].insert_many(rewards_to_insert)
    collections['transactions'].insert_many(transactions_to_insert)
    print(f"✅ Inserted {len(rewards_to_insert)} sample rewards and transactions.")


def create_mood_entries(family_id, child_ids):
    """Generates daily mood entries using timezone-aware dates."""
    print("\n--- 😊 Generating Mood Entries ---")
    family_oid = ObjectId(family_id)
    today = now_est().date()
    moods_to_insert = []

    for child_id in child_ids:
        for day in range(NUM_DAYS_HISTORY):
            current_date_obj = today - timedelta(days=day)
            current_date_dt = start_of_day_est(current_date_obj) # Use EST midnight
            for period in ['Morning', 'Afternoon', 'Evening']:
                if random.random() < 0.75:
                    mood_choice = random.choices(MOOD_CONFIG['moods'], weights=[0.1, 0.2, 0.5, 0.2], k=1)[0]
                    moods_to_insert.append({
                        'user_id': ObjectId(child_id), 'family_id': family_oid, 'date': current_date_dt,
                        'period': period, 'mood_emoji': mood_choice['emoji'], 'mood_score': mood_choice['score'],
                        'note': random.choice(mood_choice['notes']) if random.random() < 0.3 else ""
                    })

    if moods_to_insert:
        collections['moods'].insert_many(moods_to_insert)
        print(f"✅ Inserted {len(moods_to_insert)} mood entries.")

def create_direct_messages(family_id, parent_ids, child_ids_map):
    """Creates conversation history, including a new unread message for a parent."""
    print("\n--- 💬 Generating Direct Messages ---")
    family_oid = ObjectId(family_id)
    parent1_obj = collections['users'].find_one({'_id': ObjectId(parent_ids[0])})
    child1_id, child1_name = list(child_ids_map.items())[0]

    messages_to_insert = [
        # Historical read message
        {
            "family_id": family_oid, "sender_id": ObjectId(child1_id), "sender_username": child1_name,
            "recipient_id": parent1_obj['_id'], "message_content": "I finished my reading for today!",
            "sent_at": now_est() - timedelta(days=1, hours=5), "is_read": True
        },
        {
            "family_id": family_oid, "sender_id": parent1_obj['_id'], "sender_username": parent1_obj['username'],
            "recipient_id": ObjectId(child1_id), "message_content": "That's awesome, great job!",
            "sent_at": now_est() - timedelta(days=1, hours=4), "is_read": True
        },
        # New UNREAD message
        {
            "family_id": family_oid, "sender_id": ObjectId(child1_id), "sender_username": child1_name,
            "recipient_id": parent1_obj['_id'], "message_content": "Quick question: Can I have a friend over Saturday?",
            "sent_at": now_est() - timedelta(minutes=15), "is_read": False
        }
    ]

    collections['direct_messages'].insert_many(messages_to_insert)
    print(f"✅ Inserted {len(messages_to_insert)} sample direct messages.")

# Other functions can be simplified or used as is, just ensuring timezone usage
def create_challenges_and_timers(family_id, parent_ids, child_ids_map):
    print("\n--- 🏆 Generating Challenges & Timers ---")
    collections['challenges'].insert_one({
        "family_id": ObjectId(family_id), "title": "Yard Work Champion",
        "description": "Rake all leaves and bag them up.", "points": 150, "status": "open",
        "created_by_id": ObjectId(random.choice(parent_ids)), "created_at": now_est() - timedelta(days=2)
    })
    collections['timers'].insert_one({
        'name': "Family Vacation Countdown", 'end_date': now_est() + timedelta(days=45),
        'family_id': ObjectId(family_id), 'created_by': ObjectId(random.choice(parent_ids + list(child_ids_map.keys())))
    })
    print("✅ Inserted 1 challenge and 1 timer.")

###############################################################################
# Main Seeding Routine
###############################################################################
def seed_database():
    """Main function orchestrating the database seeding process."""
    print(f"--- 🚀 Starting Database Seeding for '{DB_NAME}' ---")
    confirm = input(f"⚠️  This will DELETE ALL DATA in '{DB_NAME}'. Type 'yes' to continue: ")
    if confirm.lower() != 'yes':
        print("\nSeeding cancelled by user.")
        return

    # 1. Clear all existing data
    clear_collections()

    # 2. Create family structure
    family_id, parent_ids, child_ids = create_family_members()
    child_docs = list(collections['users'].find({'_id': {'$in': [ObjectId(cid) for cid in child_ids]}}))
    child_ids_map = {str(doc['_id']): doc['username'] for doc in child_docs}

    # 3. Create interconnected data
    create_events_and_history(family_id, child_ids)
    create_rewards_and_transactions(family_id, child_ids_map)
    create_mood_entries(family_id, child_ids)
    create_direct_messages(family_id, parent_ids, child_ids_map)
    create_challenges_and_timers(family_id, parent_ids, child_ids_map)

    print("\n--- 🎉 Database Seeding Complete! ---")
    print("Sample logins:")
    print("  • Parent 1: dad@example.com / password123")
    print("  • Parent 2: mom@example.com / password123")
    print("  • Child 1: Leo / password123")
    print("  • Child 2: Mia / password123")

if __name__ == '__main__':
    seed_database()