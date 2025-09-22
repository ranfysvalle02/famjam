# seed_db.py
# This script populates the MongoDB database with some initial data.
# Run this once before starting the Flask application for the first time.
# python seed_db.py

from pymongo import MongoClient
from flask_bcrypt import Bcrypt
import os

# Create a dummy Flask app context to use Bcrypt
# This is just to get access to the bcrypt functions
dummy_app_for_bcrypt = type('DummyApp', (object,), {'config': {}})() 
bcrypt = Bcrypt(dummy_app_for_bcrypt)

# --- Database Connection ---
client = MongoClient('mongodb://localhost:27017/?retryWrites=true&w=majority&directConnection=true')
db = client['chore_app']
users_collection = db['users']
chores_collection = db['chores']

def seed_database():
    """Clears existing data and populates the database with sample data."""
    print("Clearing existing users and chores collections...")
    users_collection.delete_many({})
    chores_collection.delete_many({})

    print("Seeding database...")

    # --- Create a Parent User ---
    parent_email = "parent@example.com"
    parent_password = "password123"
    hashed_password = bcrypt.generate_password_hash(parent_password).decode('utf-8')
    
    parent_doc = {
        'email': parent_email,
        'password_hash': hashed_password,
        'role': 'parent',
        'points': 0 
    }
    parent_id_obj = users_collection.insert_one(parent_doc).inserted_id
    parent_id_str = str(parent_id_obj)
    
    # A parent's family_id is their own user ID
    users_collection.update_one({'_id': parent_id_obj}, {'$set': {'family_id': parent_id_str}})
    print(f"Created parent user: {parent_email} (password: {parent_password})")
    print(f"Parent's Invite Code is: {parent_id_str}")


    # --- Create Child Users ---
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
    child1_id = users_collection.insert_one(child1_doc).inserted_id
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
    child2_id = users_collection.insert_one(child2_doc).inserted_id
    print(f"Created child user: {child2_username} (password: {child2_password})")


    # --- Create Chores ---
    chores_data = [
        {
            'name': 'Clean Room',
            'description': 'Tidy up, make the bed, and put away all clothes.',
            'points': 50,
            'family_id': parent_id_str,
            'status': 'assigned',
            'assigned_to': str(child1_id)
        },
        {
            'name': 'Wash Dishes',
            'description': 'Wash and dry all dishes from dinner.',
            'points': 30,
            'family_id': parent_id_str,
            'status': 'completed',
            'assigned_to': str(child2_id)
        },
        {
            'name': 'Walk the Dog',
            'description': 'Take the dog for a 20-minute walk around the block.',
            'points': 25,
            'family_id': parent_id_str,
            'status': 'pending'
        },
        {
            'name': 'Take Out Trash',
            'description': 'Empty all trash cans and take the bags to the curb.',
            'points': 10,
            'family_id': parent_id_str,
            'status': 'approved',
            'assigned_to': str(child1_id)
        }
    ]
    chores_collection.insert_many(chores_data)
    print(f"Inserted {len(chores_data)} sample chores.")
    
    print("\nDatabase seeding complete!")


if __name__ == '__main__':
    seed_database()
