# seed_db.py
# This enhanced script populates the MongoDB database with dynamic, realistic sample data.
# It sets up a sample family, generates an active FamJam plan,
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
DB_NAME = 'mchores_app'
NUM_DAYS_HISTORY = 45 # Generate a richer history

# Mood configuration, mirroring the main app for consistency
MOOD_CONFIG = {
    'moods': [
        {'emoji': '😖', 'desc': 'Upset', 'score': 1, 'notes': ["Felt overwhelmed today.", "Had a disagreement.", "Just a tough morning."]},
        {'emoji': '😔', 'desc': 'Not Happy', 'score': 2, 'notes': ["A bit tired and bored.", "Missing my friends.", "Wish I could play outside."]},
        {'emoji': '😌', 'desc': 'Calm / Okay', 'score': 3, 'notes': ["Just a normal day.", "Feeling pretty good.", "Listened to music."]},
        {'emoji': '😎', 'desc': 'Very Happy', 'score': 4, 'notes': ["Had a great time with family!", "Excited for the weekend!", "Finished a cool project."]}
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
    client.server_info()
    print(f"✅ MongoDB connection successful to '{MONGO_URI}'.")
except Exception as e:
    print(f"❌ Error connecting to MongoDB: {e}")
    print("Please ensure MongoDB is running and the MONGO_URI is correct.")
    exit()

def clear_collections():
    """Clears all relevant collections for a fresh start."""
    print("🗑️  Clearing existing data from all collections...")
    collections = [
        users_collection, events_collection, rewards_collection,
        transactions_collection, moods_collection, famjam_plans_collection
    ]
    for collection in collections:
        collection.delete_many({})
    print("✨ Collections cleared.")

def create_family_members():
    """Creates a parent and two children with varied point totals."""
    print("\n--- 👨‍👩‍👧‍👦 Creating Family Members ---")
    parent_email = "parent@example.com"
    parent_username = "ParentUser"
    parent_password = "password123"
    hashed_password = bcrypt.generate_password_hash(parent_password).decode('utf-8')

    parent_doc = {
        'email': parent_email, 'username': parent_username,
        'password_hash': hashed_password, 'role': 'parent', 'points': 0, 'lifetime_points': 0
    }
    parent_id_obj = users_collection.insert_one(parent_doc).inserted_id
    parent_id_str = str(parent_id_obj)
    users_collection.update_one({'_id': parent_id_obj}, {'$set': {'family_id': parent_id_str}})
    print(f"👤 Parent created -> email: {parent_email}, password: {parent_password}")
    print(f"🔑 Parent's Invite Code: {parent_id_str}")

    children_data = [
        {"username": "Alex", "password": "password123", "points": random.randint(120, 250), "lifetime_points": random.randint(300, 500)},
        {"username": "Bella", "password": "password123", "points": random.randint(200, 350), "lifetime_points": random.randint(500, 800)}
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
        print(f"👤 Child created  -> username: {child['username']}, password: {child['password']}")

    return parent_id_str, child_ids

def create_famjam_plan_and_events(parent_id, child_ids):
    """Creates an active FamJam plan and generates all associated chore events for the current calendar quarter."""
    print("\n--- 🗓️  Generating FamJam Plan & Chore History ---")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # --- FIX: Use the same fixed-quarter logic as app.py ---
    # Determine the current calendar quarter
    current_quarter = (today.month - 1) // 3 + 1
    start_month = (current_quarter - 1) * 3 + 1
    
    # Calculate the start and end dates for the CURRENT quarter
    start_date = today.replace(month=start_month, day=1)
    end_date = start_date + relativedelta(months=3) - timedelta(days=1)
    # --- END FIX ---

    sample_plan_data = {
        "plan_name": f"Teamwork Makes the Dream Work (Q{current_quarter})",
        "suggested_chores": [
            {"name": "Morning Kitchen Reset", "description": "Unload dishwasher, wipe counters, and sweep the floor.", "points": 15, "type": "chore", "recurrence": "daily"},
            {"name": "Evening Pet Care", "description": "Feed the pets, check their water, and give them some attention.", "points": 10, "type": "chore", "recurrence": "daily"},
            {"name": "Tidy Your Bedroom", "description": "Make your bed, put away clothes, and clear your desk.", "points": 10, "type": "chore", "recurrence": "daily"},
            {"name": "Weekly Bathroom Clean", "description": "Wipe sink and mirror, tidy towels, and clean the toilet.", "points": 40, "type": "chore", "recurrence": "weekly"},
            {"name": "Recycling & Trash Duty", "description": "Take all bins out for collection day and bring them back in.", "points": 25, "type": "chore", "recurrence": "weekly"},
        ]
    }

    # Insert the active plan for the current quarter
    famjam_plans_collection.insert_one({
        'plan_data': sample_plan_data, 'family_id': parent_id, 'status': 'active',
        'start_date': start_date, 'end_date': end_date, 'created_at': start_date - timedelta(days=2), 'applied_at': start_date
    })
    
    # Insert an archived plan for the PREVIOUS quarter for historical context
    last_quarter_start = start_date - relativedelta(months=3)
    last_quarter_end = start_date - timedelta(days=1)
    famjam_plans_collection.insert_one({
        'plan_data': {"plan_name": "Old Summer Plan", "suggested_chores": []}, 'family_id': parent_id, 'status': 'archived',
        'start_date': last_quarter_start, 'end_date': last_quarter_end, 'created_at': last_quarter_start - timedelta(days=1),
    })

    # --- Generate events based on the active plan ---
    child_cycler = itertools.cycle(child_ids)
    events_to_insert = []

    for chore in sample_plan_data["suggested_chores"]:
        delta = timedelta(days=1) if chore['recurrence'] == 'daily' else timedelta(weeks=1)
        current_due_date = start_date
        while current_due_date <= end_date:
            assigned_child_id = next(child_cycler)
            doc = {**chore, 'family_id': parent_id, 'assigned_to': assigned_child_id, 'due_date': current_due_date, 'source': 'FamJamPlan', 'source_type': 'generated'}
            
            if current_due_date < today: # For past events, set a realistic status
                roll = random.random()
                if roll < 0.85: # Approved
                    doc['status'] = 'approved'
                    doc['approved_at'] = current_due_date + timedelta(hours=random.randint(2, 26))
                elif roll < 0.95: # Completed, pending approval
                    doc['status'] = 'completed'
                else: # Missed
                    doc['status'] = 'assigned' # Remains assigned if missed
            else:
                doc['status'] = 'assigned'
            
            events_to_insert.append(doc)
            current_due_date += delta
            
    if events_to_insert:
        events_collection.insert_many(events_to_insert)
        print(f"✅ Inserted {len(events_to_insert)} FamJam chore events for the current quarter.")

def create_ad_hoc_events_and_habits(parent_id, child_ids):
    """Generates a history of manually added chores and habits."""
    print("\n--- 🧩 Generating Ad-hoc Chores & Habits ---")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    events_to_insert = []
    
    sample_habits = [
        {'name': 'Practice Piano', 'description': 'Complete a 15-minute practice session.', 'points': 15, 'assigned_to': child_ids[0]},
        {'name': 'Read for 20 Minutes', 'description': 'Read a book, not a screen!', 'points': 20, 'assigned_to': child_ids[1]},
        {'name': 'Water the Plants', 'description': 'Check indoor plants and water if needed.', 'points': 5, 'assigned_to': child_ids[0]}
    ]
    for habit in sample_habits:
        streak = random.randint(3, 12)
        last_completed = today - timedelta(days=random.choice([1, 2, 3])) # Creates varied streak states
        events_to_insert.append({**habit, 'type': 'habit', 'family_id': parent_id, 'status': 'assigned', 'due_date': today - timedelta(days=60), 'streak': streak, 'last_completed': last_completed})

    one_off_chores = [
        {'name': 'Organize Garage Shelf', 'points': 50}, {'name': 'Wash the Car', 'points': 75},
        {'name': 'Help with Grocery Shopping', 'points': 25}, {'name': 'Rake Leaves in Backyard', 'points': 60}
    ]
    for _ in range(5):
        chore = random.choice(one_off_chores)
        due_date = today - timedelta(days=random.randint(1, NUM_DAYS_HISTORY))
        events_to_insert.append({**chore, 'type': 'chore', 'family_id': parent_id, 'status': 'approved', 'assigned_to': random.choice(child_ids), 'due_date': due_date, 'approved_at': due_date + timedelta(hours=8)})

    if events_to_insert:
        events_collection.insert_many(events_to_insert)
        print(f"✅ Inserted {len(events_to_insert)} ad-hoc events (habits and one-off chores).")

def create_rewards_and_transactions(parent_id, child_ids_map):
    """Generates a history of reward requests and transactions."""
    print("\n--- 🎁 Generating Rewards & Transactions ---")
    today = datetime.utcnow()
    docs = []
    
    sample_rewards = [
        {'name': 'One Hour of Video Games', 'cost': 100}, {'name': 'New Book ($15 limit)', 'cost': 200},
        {'name': 'Movie Night Choice', 'cost': 150}, {'name': 'Ice Cream Outing', 'cost': 250},
        {'name': 'Stay Up 30 Mins Later', 'cost': 75}
    ]

    for _ in range(10):
        reward = random.choice(sample_rewards)
        child_id = random.choice(list(child_ids_map.keys()))
        child_username = child_ids_map[child_id]
        
        status = random.choices(['approved', 'rejected', 'requested'], weights=[0.7, 0.15, 0.15], k=1)[0]
        spent_at = today - timedelta(days=random.randint(0, NUM_DAYS_HISTORY), hours=random.randint(1, 23))
        resolved_at = spent_at + timedelta(hours=random.randint(4, 24)) if status != 'requested' else None
        
        reward_id = ObjectId()
        docs.append((
            rewards_collection, {
                '_id': reward_id, 'name': reward['name'], 'points_cost': reward['cost'], 'family_id': parent_id,
                'requested_by_id': child_id, 'status': status, 'resolved_at': resolved_at
            }
        ))
        docs.append((
            transactions_collection, {
                'reward_id': reward_id, 'family_id': parent_id, 'child_id': child_id, 'child_username': child_username,
                'reward_name': reward['name'], 'points_spent': reward['cost'], 'status': status if status != 'requested' else 'pending',
                'spent_at': spent_at, 'resolved_at': resolved_at
            }
        ))

    for collection, doc in docs:
        collection.insert_one(doc)
    print(f"✅ Inserted {len(docs)//2} sample rewards and transactions.")

def create_mood_entries(parent_id, child_ids):
    """Generates a plausible history of mood entries for each child."""
    print("\n--- 😊 Generating Mood Entries ---")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    moods_to_insert = []
    
    for child_id in child_ids:
        for day in range(NUM_DAYS_HISTORY):
            current_date = today - timedelta(days=day)
            for period in ['Morning', 'Afternoon', 'Evening']:
                if random.random() < 0.75: # 75% chance to log a mood for a given period
                    mood = random.choices(MOOD_CONFIG['moods'], weights=[0.1, 0.2, 0.5, 0.2], k=1)[0]
                    note = random.choice(mood['notes']) if random.random() < 0.3 else ""
                    moods_to_insert.append({
                        'user_id': ObjectId(child_id), 'family_id': ObjectId(parent_id),
                        'date': current_date, 'period': period, 'mood_emoji': mood['emoji'],
                        'mood_score': mood['score'], 'note': note, 'created_at': current_date, 'updated_at': current_date
                    })

    if moods_to_insert:
        moods_collection.insert_many(moods_to_insert)
        print(f"✅ Inserted {len(moods_to_insert)} sample mood entries.")

def seed_database():
    """Main function to orchestrate the database seeding."""
    print(f"--- 🚀 Starting Database Seeding for '{DB_NAME}' ---")
    
    confirm = input(f"⚠️  This will WIPE ALL DATA in the '{DB_NAME}' database. Are you sure? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Seeding cancelled by user.")
        return

    clear_collections()
    
    parent_id, child_ids = create_family_members()
    child_docs = list(users_collection.find({'_id': {'$in': [ObjectId(cid) for cid in child_ids]}}))
    child_ids_map = {str(doc['_id']): doc['username'] for doc in child_docs}
    
    create_famjam_plan_and_events(parent_id, child_ids)
    create_ad_hoc_events_and_habits(parent_id, child_ids)
    create_rewards_and_transactions(parent_id, child_ids_map)
    create_mood_entries(parent_id, child_ids)

    print("\n--- 🎉 Database seeding complete! ---")
    print("You can now run the main application (`python app.py`).")

if __name__ == '__main__':
    seed_database()