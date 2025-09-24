# seed_db.py
# This enhanced script populates the MongoDB database with dynamic, realistic sample data.
# It sets up a sample family and generates 30 days of historical data for chores,
# habits, rewards, and mood entries to fully populate all dashboards.
#
# Usage: python seed_db.py

import os
import random
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
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
NUM_DAYS_HISTORY = 30 # Generate data for the last 30 days

# Mood configuration, mirroring the main app for consistency
MOOD_OPTIONS = [
    {'emoji': '😖', 'desc': 'Upset', 'score': 1},
    {'emoji': '😔', 'desc': 'Not Happy', 'score': 2},
    {'emoji': '😌', 'desc': 'Calm / Okay', 'score': 3},
    {'emoji': '😎', 'desc': 'Very Happy', 'score': 4}
]

# --- Database Setup ---
try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db['users']
    events_collection = db['events']
    rewards_collection = db['rewards']
    transactions_collection = db['transactions']
    moods_collection = db['moods'] # New collection for MoodMatrix
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

def create_chores_and_habits(parent_id, child_ids):
    """Generates a history of chores and habits for the children."""
    print("\n--- Generating Chores & Habits ---")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    events_to_insert = []
    
    sample_chores = [
        {'name': 'Tidy Up Bedroom', 'desc': 'Make the bed, put away clothes and toys.', 'points': 25},
        {'name': 'Water the Plants', 'desc': 'Give water to all the indoor plants.', 'points': 20},
        {'name': 'Take Out Recycling', 'desc': 'Empty all recycling bins into the main container.', 'points': 15},
        {'name': 'Feed the Dog', 'desc': 'Fill the dog\'s food and water bowls.', 'points': 10},
        {'name': 'Set the Dinner Table', 'desc': 'Put out plates, cutlery, and glasses for dinner.', 'points': 10}
    ]
    
    sample_habits = [
        {'name': 'Practice Piano', 'desc': 'Complete a 15-minute practice session.', 'points': 10},
        {'name': 'Read for 20 minutes', 'desc': 'Read a book, not a screen!', 'points': 15}
    ]

    # Create habits that have been active for a while
    for habit_template in sample_habits:
        child_id = random.choice(child_ids)
        start_date = today - timedelta(days=random.randint(20, 30))
        last_completed = today - timedelta(days=random.randint(1, 3))
        events_to_insert.append({
            **habit_template, 'description': habit_template['desc'], 'type': 'habit', 'family_id': parent_id,
            'status': 'assigned', 'assigned_to': child_id, 'created_at': start_date,
            'due_date': start_date, 'streak': random.randint(0, 5), 'last_completed': last_completed
        })

    # Create a history of chores over the last month
    for day in range(NUM_DAYS_HISTORY):
        # Add 1-2 chores per day to make it look active
        for _ in range(random.randint(1, 2)):
            chore = random.choice(sample_chores)
            child_id = random.choice(child_ids)
            created_date = today - timedelta(days=day + random.randint(1,3))
            due_date = today - timedelta(days=day)
            
            # Randomly determine the status to create a mix of data
            status_roll = random.random()
            if status_roll < 0.6: # 60% are approved
                status = 'approved'
                approved_at = due_date + timedelta(hours=random.randint(4, 28))
            elif status_roll < 0.85: # 25% are completed (pending)
                status = 'completed'
                approved_at = None
            else: # 15% are still assigned
                status = 'assigned'
                approved_at = None

            events_to_insert.append({
                'name': chore['name'], 'description': chore['desc'], 'points': chore['points'],
                'type': 'chore', 'family_id': parent_id, 'status': status,
                'assigned_to': child_id, 'created_at': created_date, 'due_date': due_date,
                'approved_at': approved_at
            })

    if events_to_insert:
        events_collection.insert_many(events_to_insert)
        print(f"Inserted {len(events_to_insert)} sample events.")

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
        {'name': 'Ice Cream Outing', 'cost': 250}
    ]

    for _ in range(5): # Create 5 historical reward transactions
        reward = random.choice(sample_rewards)
        child_id = random.choice(list(child_ids_map.keys()))
        child_username = child_ids_map[child_id]
        
        status_roll = random.random()
        if status_roll < 0.6: status = 'approved'
        elif status_roll < 0.85: status = 'rejected'
        else: status = 'requested'
        
        spent_at = today - timedelta(days=random.randint(1, 28), hours=random.randint(1, 23))
        resolved_at = spent_at + timedelta(days=1) if status != 'requested' else None

        reward_id = ObjectId()
        rewards_to_create.append({
            '_id': reward_id, 'name': reward['name'], 'points_cost': reward['cost'],
            'family_id': parent_id, 'requested_by_id': child_id, 'status': status,
            'resolved_at': resolved_at
        })
        transactions_to_create.append({
            'reward_id': reward_id, 'family_id': parent_id, 'child_id': child_id,
            'child_username': child_username, 'reward_name': reward['name'],
            'points_spent': reward['cost'], 'status': 'pending' if status == 'requested' else status,
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
    
    for child_id in child_ids:
        for day in range(NUM_DAYS_HISTORY):
            current_date = today - timedelta(days=day)
            for period in ['AM', 'PM']:
                # Simulate that users don't log their mood every single time
                if random.random() < 0.8: # 80% chance to log a mood for a given period
                    mood = random.choice(MOOD_OPTIONS)
                    moods_to_insert.append({
                        'user_id': ObjectId(child_id),
                        'family_id': ObjectId(parent_id),
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
    
    create_chores_and_habits(parent_id, child_ids)
    create_rewards_and_transactions(parent_id, child_ids_map)
    create_mood_entries(parent_id, child_ids)

    print("\n--- Database seeding complete! ---")
    print("You can now run the main application (`python app.py`).")


if __name__ == '__main__':
    seed_database()
