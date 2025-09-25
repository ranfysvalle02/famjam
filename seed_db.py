# seed_db.py
# This enhanced script populates the MongoDB database with dynamic, realistic sample data.
# It sets up a sample family, generates an active 90-day FamJam plan,
# and creates a rich history for chores, habits, rewards, and moods to fully populate all dashboards.
#
# Usage: python seed_db.py

import os
import random
import itertools
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from bson.objectid import ObjectId
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# To use bcrypt functions outside of a Flask app context, we create a simple
# class that mimics a Flask app's config.
class DummyApp:
    config = {}

bcrypt = Bcrypt(DummyApp())

# --- Database Connection ---
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
DB_NAME = 'mchores_app'  # The database name used in the main application
NUM_DAYS_HISTORY = 30 # Generate data for the last 30 days for some records

# Mood configuration, mirroring the main app for consistency
MOOD_CONFIG = {
    'moods': [
        {'emoji': '😖', 'desc': 'Upset',      'score': 1, 'color': '#ef4444'},
        {'emoji': '😔', 'desc': 'Not Happy',  'score': 2, 'color': '#f97316'},
        {'emoji': '😌', 'desc': 'Calm / Okay','score': 3, 'color': '#84cc16'},
        {'emoji': '😎', 'desc': 'Very Happy', 'score': 4, 'color': '#22c55e'}
    ]
}

# --- Database Setup ---
try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db['users']
    events_collection = db['events']
    rewards_collection = db['rewards']
    transactions_collection = db['transactions']
    moods_collection = db['moods']
    famjam_plans_collection = db['famjam_plans']
    # Test connection
    client.server_info()
    print(f"MongoDB connection successful to '{MONGO_URI}'.")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    print("Please ensure MongoDB is running and the MONGO_URI is correct.")
    exit()

def clear_collections():
    """Clears all relevant collections for a fresh start."""
    print("Clearing existing data from all collections...")
    users_collection.delete_many({})
    events_collection.delete_many({})
    rewards_collection.delete_many({})
    transactions_collection.delete_many({})
    moods_collection.delete_many({})
    famjam_plans_collection.delete_many({})
    print("Collections cleared.")

def create_family_members():
    """Creates a standard parent and two children, returning their IDs."""
    # --- Parent User ---
    parent_email = "parent@example.com"
    parent_username = "ParentUser"
    parent_password = "password123"
    hashed_password = bcrypt.generate_password_hash(parent_password).decode('utf-8')

    parent_doc = {
        'email': parent_email, 'username': parent_username,
        'password_hash': hashed_password, 'role': 'parent',
        'points': 0, 'lifetime_points': 0
    }
    parent_id_obj = users_collection.insert_one(parent_doc).inserted_id
    parent_id_str = str(parent_id_obj)
    users_collection.update_one({'_id': parent_id_obj}, {'$set': {'family_id': parent_id_str}})

    # --- Child Users ---
    children_data = [
        {"username": "Alex", "password": "password123", "points": 150, "lifetime_points": 350},
        {"username": "Bella", "password": "password123", "points": 225, "lifetime_points": 500}
    ]
    child_ids = []
    for child in children_data:
        child_hash = bcrypt.generate_password_hash(child["password"]).decode('utf-8')
        child_doc = {
            'username': child["username"], 'password_hash': child_hash, 'role': 'child',
            'family_id': parent_id_str, 'points': child["points"], 'lifetime_points': child["lifetime_points"]
        }
        child_id_obj = users_collection.insert_one(child_doc).inserted_id
        child_ids.append(str(child_id_obj))

    print("\n--- Family Members Created ---")
    print(f"Parent -> email: {parent_email}, username: {parent_username}, password: {parent_password}")
    print(f"Parent's Invite Code: {parent_id_str}")
    for i, child in enumerate(children_data):
        print(f"Child {i+1} -> username: {child['username']}, password: {child['password']}")

    return parent_id_str, child_ids

def create_famjam_plan_and_events(parent_id, child_ids):
    """Creates an active FamJam plan and generates all associated chore events for a 90-day period."""
    print("\n--- Generating FamJam Plan & Chore History ---")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Create a plan that started 45 days ago to have a good mix of past and future events
    start_date = today - timedelta(days=45)
    end_date = start_date + timedelta(days=90)

    sample_plan_data = {
        "plan_name": f"Family Goals - Q{ (start_date.month - 1) // 3 + 1 } {start_date.year}",
        "suggested_chores": [
            {"name": "Morning Kitchen Reset", "description": "Unload dishwasher, wipe counters.", "points": 15, "type": "chore", "recurrence": "daily"},
            {"name": "Evening Pet Care", "description": "Feed the pets and check their water.", "points": 10, "type": "chore", "recurrence": "daily"},
            {"name": "Weekly Room Tidy", "description": "Full clean of bedroom: dust, vacuum, organize.", "points": 50, "type": "chore", "recurrence": "weekly"},
            {"name": "Recycling & Trash Duty", "description": "Take all bins out for collection day.", "points": 25, "type": "chore", "recurrence": "weekly"},
            {"name": "Garden Weeding", "description": "Spend 20 minutes pulling weeds.", "points": 30, "type": "chore", "recurrence": "weekly"},
        ]
    }

    # Insert an active plan
    famjam_plans_collection.insert_one({
        'plan_data': sample_plan_data, 'family_id': parent_id, 'status': 'active',
        'start_date': start_date, 'end_date': end_date, 'created_at': start_date - timedelta(days=1),
        'applied_at': start_date
    })
    
    # Insert an archived plan for historical context
    last_quarter_start = start_date - relativedelta(months=3)
    famjam_plans_collection.insert_one({
        'plan_data': {"plan_name": "Old Plan", "suggested_chores": []}, 'family_id': parent_id, 'status': 'archived',
        'start_date': last_quarter_start, 'end_date': start_date - timedelta(days=1), 'created_at': last_quarter_start - timedelta(days=1),
    })

    # --- Generate events based on the active plan ---
    child_cycler = itertools.cycle(child_ids)
    events_to_insert = []

    for chore_template in sample_plan_data["suggested_chores"]:
        recurrence = chore_template.get('recurrence', '').lower()
        if recurrence == 'daily': delta = timedelta(days=1)
        elif recurrence == 'weekly': delta = timedelta(weeks=1)
        else: continue

        current_due_date = start_date
        while current_due_date < end_date:
            assigned_child_id = next(child_cycler)
            status = 'assigned'
            approved_at = None

            # For past events, randomly mark them as approved or completed
            if current_due_date < today:
                status_roll = random.random()
                if status_roll < 0.85: # 85% are approved
                    status = 'approved'
                    approved_at = current_due_date + timedelta(hours=random.randint(4, 28))
                else: # 15% are completed but pending
                    status = 'completed'
            
            doc = {
                **chore_template, 'description': chore_template.get('description'),
                'family_id': parent_id, 'status': status, 'created_at': current_due_date - timedelta(days=1),
                'assigned_to': assigned_child_id, 'due_date': current_due_date, 'source': 'FamJamPlan', 'source_type': 'generated',
                'approved_at': approved_at
            }
            events_to_insert.append(doc)
            current_due_date += delta
    
    if events_to_insert:
        events_collection.insert_many(events_to_insert)
        print(f"Inserted {len(events_to_insert)} FamJam Plan-based chore events.")

def create_ad_hoc_events(parent_id, child_ids):
    """Generates a history of ad-hoc (non-plan) chores and habits."""
    print("\n--- Generating Ad-hoc Chores & Habits ---")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    events_to_insert = []
    
    sample_habits = [
        {'name': 'Practice Piano', 'description': 'Complete a 15-minute practice session.', 'points': 10},
        {'name': 'Read for 20 minutes', 'description': 'Read a book, not a screen!', 'points': 15}
    ]

    # Create habits that have been active for a while
    for habit_template in sample_habits:
        child_id = random.choice(child_ids)
        start_date = today - timedelta(days=random.randint(25, 40))
        # Make last completed date realistic based on streak
        streak = random.randint(3, 10)
        last_completed = today - timedelta(days=random.choice([1, 2])) # Completed recently to keep streak alive
        
        events_to_insert.append({
            **habit_template, 'type': 'habit', 'family_id': parent_id, 'status': 'assigned',
            'assigned_to': child_id, 'created_at': start_date, 'due_date': start_date,
            'streak': streak, 'last_completed': last_completed
        })
    
    # Create a few one-off chores
    for _ in range(10):
        chore = {'name': 'Special Task: Organize Garage Shelf', 'description': 'Help clear and organize one shelf.', 'points': 40}
        child_id = random.choice(child_ids)
        due_date = today - timedelta(days=random.randint(1, NUM_DAYS_HISTORY))
        events_to_insert.append({
            **chore, 'type': 'chore', 'family_id': parent_id, 'status': 'approved',
            'assigned_to': child_id, 'created_at': due_date - timedelta(days=1),
            'due_date': due_date, 'approved_at': due_date + timedelta(hours=8)
        })

    if events_to_insert:
        events_collection.insert_many(events_to_insert)
        print(f"Inserted {len(events_to_insert)} ad-hoc events (habits and one-off chores).")


def create_rewards_and_transactions(parent_id, child_ids_map):
    """Generates a history of reward requests and transactions."""
    print("\n--- Generating Rewards & Transactions ---")
    today = datetime.utcnow()
    rewards_to_create = []
    transactions_to_create = []

    sample_rewards = [
        {'name': 'One Hour of Video Games', 'cost': 100},
        {'name': 'New Book', 'cost': 200},
        {'name': 'Movie Night Choice', 'cost': 150},
        {'name': 'Ice Cream Outing', 'cost': 250},
        {'name': 'Sleepover with a Friend', 'cost': 300},
        {'name': 'Stay Up 30 Mins Later', 'cost': 75}
    ]

    for _ in range(8): # Create 8 historical reward transactions
        reward = random.choice(sample_rewards)
        child_id = random.choice(list(child_ids_map.keys()))
        child_username = child_ids_map[child_id]
        
        status_roll = random.random()
        if status_roll < 0.6: status = 'approved'
        elif status_roll < 0.85: status = 'rejected'
        else: status = 'requested'
        
        spent_at = today - timedelta(days=random.randint(1, 28), hours=random.randint(1, 23))
        resolved_at = spent_at + timedelta(hours=random.randint(4, 24)) if status != 'requested' else None
        
        # The transaction status should mirror the final reward status
        transaction_status = 'pending' if status == 'requested' else status

        reward_id = ObjectId()
        rewards_to_create.append({
            '_id': reward_id, 'name': reward['name'], 'points_cost': reward['cost'],
            'family_id': parent_id, 'requested_by_id': child_id, 'status': status,
            'resolved_at': resolved_at
        })
        transactions_to_create.append({
            'reward_id': reward_id, 'family_id': parent_id, 'child_id': child_id,
            'child_username': child_username, 'reward_name': reward['name'],
            'points_spent': reward['cost'], 'status': transaction_status,
            'spent_at': spent_at, 'resolved_at': resolved_at
        })
    
    if rewards_to_create:
        rewards_collection.insert_many(rewards_to_create)
        transactions_collection.insert_many(transactions_to_create)
        print(f"Inserted {len(rewards_to_create)} sample rewards and transactions.")

def create_mood_entries(parent_id, child_ids):
    """Generates a plausible history of mood entries for each child."""
    print("\n--- Generating Mood Entries ---")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    moods_to_insert = []
    
    mood_options = MOOD_CONFIG['moods']

    for child_id in child_ids:
        for day in range(NUM_DAYS_HISTORY):
            current_date = today - timedelta(days=day)
            for period in ['Morning', 'Afternoon', 'Evening']:
                # Simulate that users don't log their mood every single time
                if random.random() < 0.8: # 80% chance to log a mood for a given period
                    mood = random.choice(mood_options)
                    moods_to_insert.append({
                        'user_id': ObjectId(child_id),
                        'family_id': ObjectId(parent_id), # Note: family_id is an ObjectId in this collection
                        'date': current_date,
                        'period': period,
                        'mood_emoji': mood['emoji'],
                        'mood_score': mood['score'],
                        'note': f"Feeling {mood['desc'].lower()} today." if random.random() < 0.25 else "",
                        'created_at': current_date,
                        'updated_at': current_date
                    })

    if moods_to_insert:
        moods_collection.insert_many(moods_to_insert)
        print(f"Inserted {len(moods_to_insert)} sample mood entries.")


def seed_database():
    """Main function to orchestrate the database seeding."""
    print(f"--- Starting Database Seeding for '{DB_NAME}' ---")
    
    # SAFETY CHECK: Confirm before wiping data
    confirm = input(f"This will wipe all data in the '{DB_NAME}' database. Are you sure? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Seeding cancelled by user.")
        return

    clear_collections()
    
    parent_id, child_ids = create_family_members()
    
    child_docs = list(users_collection.find({'_id': {'$in': [ObjectId(cid) for cid in child_ids]}}))
    child_ids_map = {str(doc['_id']): doc['username'] for doc in child_docs}
    
    # Generate the structured, recurring chores from a plan
    create_famjam_plan_and_events(parent_id, child_ids)
    
    # Add supplemental habits and one-off chores
    create_ad_hoc_events(parent_id, child_ids)

    # Add rewards and transactions history
    create_rewards_and_transactions(parent_id, child_ids_map)
    
    # Add mood history
    create_mood_entries(parent_id, child_ids)

    print("\n--- Database seeding complete! ---")
    print("You can now run the main application (`python app.py`).")


if __name__ == '__main__':
    seed_database()
