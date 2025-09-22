# seed_db.py
# This script populates the MongoDB database with initial data for the mChores app.
# It sets up a sample family with a parent, two children, and a mix of chores, habits,
# and reward transactions.
#
# Run this once before starting the Flask application for the first time.
#
# Usage: python seed_db.py

from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import os
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
# Ensure your MongoDB server is running.
# Uses an environment variable for the URI if available, otherwise defaults to localhost.
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
DB_NAME = 'mchores_app' # The database name used in the main application

try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db['users']
    events_collection = db['events']
    rewards_collection = db['rewards']
    transactions_collection = db['transactions']
    # Test connection
    client.server_info() 
    print("MongoDB connection successful.")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    print("Please ensure MongoDB is running and the MONGO_URI is correct.")
    exit()


def seed_database():
    """Clears existing data and populates the database with sample data."""
    print(f"--- Starting Database Seeding for '{DB_NAME}' ---")
    
    # Clear existing collections for a fresh start
    print("Clearing existing users, events, rewards, and transactions collections...")
    users_collection.delete_many({})
    events_collection.delete_many({})
    rewards_collection.delete_many({})
    transactions_collection.delete_many({})

    # --- 1. Create a Parent User ---
    parent_email = "parent@example.com"
    parent_username = "ParentUser"
    parent_password = "password123"
    hashed_password = bcrypt.generate_password_hash(parent_password).decode('utf-8')
    
    parent_doc = {
        'email': parent_email,
        'username': parent_username,
        'password_hash': hashed_password,
        'role': 'parent',
        'points': 0,
        'lifetime_points': 0
    }
    parent_id_obj = users_collection.insert_one(parent_doc).inserted_id
    parent_id_str = str(parent_id_obj)
    
    # A parent's family_id is their own user ID, which serves as the invite code.
    users_collection.update_one({'_id': parent_id_obj}, {'$set': {'family_id': parent_id_str}})
    print(f"\nCreated parent user -> email: {parent_email}, username: {parent_username}, password: {parent_password}")
    print(f"Parent's Invite Code is: {parent_id_str}")


    # --- 2. Create Child Users ---
    child1_username = "Alex"
    child1_password = "password123"
    hashed_password1 = bcrypt.generate_password_hash(child1_password).decode('utf-8')
    child1_doc = {
        'username': child1_username,
        'password_hash': hashed_password1,
        'role': 'child',
        'family_id': parent_id_str,
        'points': 150,
        'lifetime_points': 350
    }
    child1_id_obj = users_collection.insert_one(child1_doc).inserted_id
    child1_id_str = str(child1_id_obj)
    print(f"Created child user -> username: {child1_username}, password: {child1_password}")

    child2_username = "Bella"
    child2_password = "password123"
    hashed_password2 = bcrypt.generate_password_hash(child2_password).decode('utf-8')
    child2_doc = {
        'username': child2_username,
        'password_hash': hashed_password2,
        'role': 'child',
        'family_id': parent_id_str,
        'points': 225,
        'lifetime_points': 500
    }
    child2_id_obj = users_collection.insert_one(child2_doc).inserted_id
    child2_id_str = str(child2_id_obj)
    print(f"Created child user -> username: {child2_username}, password: {child2_password}")


    # --- 3. Create Events (Chores & Habits) ---
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    events_data = [
        # Chores for Alex
        {
            'name': 'Tidy Up Bedroom',
            'description': 'Make the bed, put away clothes and toys.',
            'points': 25,
            'type': 'chore',
            'family_id': parent_id_str,
            'status': 'assigned',
            'assigned_to': child1_id_str,
            'created_at': today - timedelta(days=2),
            'due_date': today
        },
        {
            'name': 'Water the Plants',
            'description': 'Give water to all the indoor plants.',
            'points': 20,
            'type': 'chore',
            'family_id': parent_id_str,
            'status': 'approved',
            'assigned_to': child1_id_str,
            'created_at': today - timedelta(days=5),
            'due_date': today - timedelta(days=3),
            'approved_at': today - timedelta(days=2, hours=4)
        },
        # Chores for Bella
        {
            'name': 'Take Out Recycling',
            'description': 'Empty all recycling bins into the main container outside.',
            'points': 15,
            'type': 'chore',
            'family_id': parent_id_str,
            'status': 'completed', # Awaiting parent approval
            'assigned_to': child2_id_str,
            'created_at': today - timedelta(days=3),
            'due_date': today - timedelta(days=1)
        },
        {
            'name': 'Feed the Dog',
            'description': 'Fill the dog\'s food and water bowls in the evening.',
            'points': 10,
            'type': 'chore',
            'family_id': parent_id_str,
            'status': 'assigned',
            'assigned_to': child2_id_str,
            'created_at': today,
            'due_date': today + timedelta(days=1)
        },
        # Habits
        {
            'name': 'Practice Piano',
            'description': 'Complete a 15-minute practice session.',
            'points': 10,
            'type': 'habit',
            'family_id': parent_id_str,
            'status': 'assigned', # Habits are always 'assigned'
            'assigned_to': child1_id_str,
            'created_at': today - timedelta(days=10),
            'due_date': today - timedelta(days=10), # Start date
            'streak': 4, # Simulate an ongoing streak
            'last_completed': today - timedelta(days=1) # Checked in yesterday
        },
        {
            'name': 'Read for 20 minutes',
            'description': 'Read a book, not a screen!',
            'points': 15,
            'type': 'habit',
            'family_id': parent_id_str,
            'status': 'assigned',
            'assigned_to': child2_id_str,
            'created_at': today - timedelta(days=15),
            'due_date': today - timedelta(days=15), # Start date
            'streak': 0, # Streak was broken
            'last_completed': today - timedelta(days=3) # Missed check-ins
        }
    ]
    events_collection.insert_many(events_data)
    print(f"\nInserted {len(events_data)} sample events (chores and habits).")
    
    # --- 4. Create Rewards & Corresponding Transactions ---
    rewards_to_create = []
    transactions_to_create = []

    # Scenario 1: Pending Reward Request from Alex
    reward1_id = ObjectId()
    rewards_to_create.append({
        '_id': reward1_id,
        'name': 'One Hour of Video Games',
        'points_cost': 100,
        'family_id': parent_id_str,
        'requested_by_id': child1_id_str,
        'status': 'requested',
        'resolved_at': None
    })
    transactions_to_create.append({
        'reward_id': reward1_id,
        'family_id': parent_id_str,
        'child_id': child1_id_str,
        'child_username': child1_username,
        'reward_name': 'One Hour of Video Games',
        'points_spent': 100,
        'status': 'pending',
        'spent_at': today - timedelta(hours=5),
        'resolved_at': None
    })
    
    # Scenario 2: Approved Reward from Bella
    reward2_id = ObjectId()
    rewards_to_create.append({
        '_id': reward2_id,
        'name': 'New Book',
        'points_cost': 200,
        'family_id': parent_id_str,
        'requested_by_id': child2_id_str,
        'status': 'approved',
        'resolved_at': today - timedelta(days=1, hours=2)
    })
    transactions_to_create.append({
        'reward_id': reward2_id,
        'family_id': parent_id_str,
        'child_id': child2_id_str,
        'child_username': child2_username,
        'reward_name': 'New Book',
        'points_spent': 200,
        'status': 'approved',
        'spent_at': today - timedelta(days=2),
        'resolved_at': today - timedelta(days=1, hours=2)
    })

    # Scenario 3: Rejected Reward from Alex
    reward3_id = ObjectId()
    rewards_to_create.append({
        '_id': reward3_id,
        'name': 'Movie Night Choice',
        'points_cost': 150,
        'family_id': parent_id_str,
        'requested_by_id': child1_id_str,
        'status': 'rejected',
        'resolved_at': today - timedelta(hours=10)
    })
    transactions_to_create.append({
        'reward_id': reward3_id,
        'family_id': parent_id_str,
        'child_id': child1_id_str,
        'child_username': child1_username,
        'reward_name': 'Movie Night Choice',
        'points_spent': 150,
        'status': 'rejected',
        'spent_at': today - timedelta(days=1),
        'resolved_at': today - timedelta(hours=10)
    })

    if rewards_to_create:
        rewards_collection.insert_many(rewards_to_create)
        print(f"Inserted {len(rewards_to_create)} sample rewards.")
    
    if transactions_to_create:
        transactions_collection.insert_many(transactions_to_create)
        print(f"Inserted {len(transactions_to_create)} sample spend transactions.")
    
    print("\n--- Database seeding complete! ---")
    print("You can now run the main application.")


if __name__ == '__main__':
    seed_database()