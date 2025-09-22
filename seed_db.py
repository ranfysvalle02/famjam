# seed_db.py
# This script populates the MongoDB database with initial data for the mChores app.
# It sets up a sample family with a parent, two children, and a mix of chores and habits.
# Run this once before starting the Flask application for the first time.
#
# Usage: python seed_db.py

from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import os

# --- Configuration ---
# To use bcrypt functions, we create a simple class that mimics a Flask app's config.
class DummyApp:
    config = {}

bcrypt = Bcrypt(DummyApp())

# --- Database Connection ---
# Ensure your MongoDB server is running.
# Uses an environment variable for the URI if available, otherwise defaults to localhost.
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
DB_NAME = 'mchores_app' # The database name used in the main application

client = MongoClient('mongodb://localhost:27017/?retryWrites=true&w=majority&directConnection=true')
db = client[DB_NAME]
users_collection = db['users']
events_collection = db['events']
rewards_collection = db['rewards']

def seed_database():
    """Clears existing data and populates the database with sample data."""
    print(f"--- Starting Database Seeding for '{DB_NAME}' ---")
    
    # Clear existing collections for a fresh start
    print("Clearing existing users, events, and rewards collections...")
    users_collection.delete_many({})
    events_collection.delete_many({})
    rewards_collection.delete_many({})

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
        'points': 0 
    }
    parent_id_obj = users_collection.insert_one(parent_doc).inserted_id
    parent_id_str = str(parent_id_obj)
    
    # A parent's family_id is their own user ID, which serves as the invite code.
    users_collection.update_one({'_id': parent_id_obj}, {'$set': {'family_id': parent_id_str}})
    print(f"\nCreated parent user: {parent_username} / {parent_email} (password: {parent_password})")
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
        'points': 150
    }
    child1_id_obj = users_collection.insert_one(child1_doc).inserted_id
    print(f"Created child user: {child1_username} (password: {child1_password})")

    child2_username = "Bella"
    child2_password = "password123"
    hashed_password2 = bcrypt.generate_password_hash(child2_password).decode('utf-8')
    child2_doc = {
        'username': child2_username,
        'password_hash': hashed_password2,
        'role': 'child',
        'family_id': parent_id_str,
        'points': 225
    }
    child2_id_obj = users_collection.insert_one(child2_doc).inserted_id
    print(f"Created child user: {child2_username} (password: {child2_password})")


    # --- 3. Create Events (Chores & Habits) ---
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    events_data = [
        # Chores
        {
            'name': 'Tidy Up Bedroom',
            'description': 'Make the bed, put away clothes and toys.',
            'points': 25,
            'type': 'chore',
            'family_id': parent_id_str,
            'status': 'assigned',
            'assigned_to': str(child1_id_obj),
            'created_at': today - timedelta(days=2),
            'due_date': today
        },
        {
            'name': 'Take Out Recycling',
            'description': 'Empty all recycling bins into the main container outside.',
            'points': 15,
            'type': 'chore',
            'family_id': parent_id_str,
            'status': 'completed', # Awaiting approval
            'assigned_to': str(child2_id_obj),
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
            'assigned_to': str(child2_id_obj),
            'created_at': today,
            'due_date': today + timedelta(days=1)
        },
        {
            'name': 'Water the Plants',
            'description': 'Give water to all the indoor plants.',
            'points': 20,
            'type': 'chore',
            'family_id': parent_id_str,
            'status': 'approved',
            'assigned_to': str(child1_id_obj),
            'created_at': today - timedelta(days=5),
            'due_date': today - timedelta(days=3),
            'approved_at': today - timedelta(days=2)
        },
        # Habits
        {
            'name': 'Practice Piano',
            'description': 'Complete a 15-minute practice session.',
            'points': 10,
            'type': 'habit',
            'family_id': parent_id_str,
            'status': 'assigned', # Habits are always 'assigned' unless removed
            'assigned_to': str(child1_id_obj),
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
            'assigned_to': str(child2_id_obj),
            'created_at': today - timedelta(days=15),
            'due_date': today - timedelta(days=15), # Start date
            'streak': 0, # Streak was broken
            'last_completed': today - timedelta(days=2) # Missed yesterday
        }
    ]
    events_collection.insert_many(events_data)
    print(f"\nInserted {len(events_data)} sample events (chores and habits).")
    
    # --- 4. Create Rewards ---
    rewards_data = [
        {
            'name': 'One Hour of Video Games',
            'points_cost': 100,
            'family_id': parent_id_str,
            'requested_by_id': str(child1_id_obj),
            'status': 'requested'
        },
        {
            'name': 'New Book',
            'points_cost': 200,
            'family_id': parent_id_str,
            'requested_by_id': str(child2_id_obj),
            'status': 'approved'
        },
         {
            'name': 'Movie Night Choice',
            'points_cost': 150,
            'family_id': parent_id_str,
            'requested_by_id': str(child2_id_obj),
            'status': 'rejected'
        }
    ]
    rewards_collection.insert_many(rewards_data)
    print(f"Inserted {len(rewards_data)} sample rewards.")
    
    print("\n--- Database seeding complete! ---")
    print("You can now run the main application: python app.py")


if __name__ == '__main__':
    seed_database()
