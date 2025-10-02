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
  
load_dotenv()  
  
###############################################################################  
# Configuration  
###############################################################################  
class DummyApp:  
    """  
    A minimal 'app' class so that we can safely initialize Flask-Bcrypt  
    without requiring a full Flask app context.  
    """  
    config = {}  
  
bcrypt = Bcrypt(DummyApp())  
  
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')  
DB_NAME = os.environ.get('DB_NAME', 'mchores_app')  
NUM_DAYS_HISTORY = 45  # Generate data for the last N days of historical logs  
  
MOOD_CONFIG = {  
    'moods': [  
        {  
            'emoji': '😖',  
            'desc': 'Upset',  
            'score': 1,  
            'notes': [  
                "Felt overwhelmed today.",  
                "Had a disagreement.",  
                "Just a tough morning."  
            ]  
        },  
        {  
            'emoji': '😔',  
            'desc': 'Not Happy',  
            'score': 2,  
            'notes': [  
                "A bit tired and bored.",  
                "Missing my friends.",  
                "Wish I could play outside."  
            ]  
        },  
        {  
            'emoji': '😌',  
            'desc': 'Calm / Okay',  
            'score': 3,  
            'notes': [  
                "Just a normal day.",  
                "Feeling pretty good.",  
                "Listened to music."  
            ]  
        },  
        {  
            'emoji': '😎',  
            'desc': 'Very Happy',  
            'score': 4,  
            'notes': [  
                "Had a great time with family!",  
                "Excited for the weekend!",  
                "Finished a cool project."  
            ]  
        }  
    ]  
}  
  
###############################################################################  
# Connect to MongoDB  
###############################################################################  
try:  
    client = MongoClient(MONGO_URI)  
    db = client[DB_NAME]  
    # Collections used by the main app  
    users_collection = db['users']  
    events_collection = db['events']  
    rewards_collection = db['rewards']  
    transactions_collection = db['transactions']  
    moods_collection = db['moods']  
    famjam_plans_collection = db['famjam_plans']  
    timers_collection = db['timers']  
    challenges_collection = db['challenges']  
    notes_collection = db['notes']  
    personal_todos_collection = db['personal_todos']  
    direct_messages_collection = db['direct_messages']  
    families_collection = db['families']  # Multi-parent / family doc support  
  
    # Test connectivity  
    client.server_info()  
    print(f"✅ MongoDB connection successful to '{MONGO_URI}', using database '{DB_NAME}'.\n")  
except Exception as e:  
    print(f"❌ Error connecting to MongoDB: {e}")  
    exit()  
  
  
###############################################################################  
# Helper Functions  
###############################################################################  
def clear_collections():  
    """  
    Clears all relevant collections for a fresh start.  
    """  
    print("🗑️  Clearing existing data from all collections...")  
    collections_to_clear = [  
        users_collection, events_collection, rewards_collection,  
        transactions_collection, moods_collection, famjam_plans_collection,  
        timers_collection, challenges_collection, notes_collection,  
        personal_todos_collection, direct_messages_collection, families_collection  
    ]  
    for collection in collections_to_clear:  
        collection.delete_many({})  
    print("✨ Collections cleared.")  
  
  
def create_family_members():  
    """  
    Creates two parents and two children linked to one Family document.  
    Returns the family_id string, and lists of parent/child IDs (as strings).  
    """  
    print("\n--- 👨‍👩‍👧‍👦 Creating Family Members (2 Parents, 2 Children) ---")  
  
    # Step 1: Create the dedicated Family document  
    family_doc_template = {  
        'name': "The Awesome Family",  
        'parent_ids': [],  
        'created_at': datetime.utcnow()  
    }  
    family_id_obj = families_collection.insert_one(family_doc_template).inserted_id  
    family_id_str = str(family_id_obj)  
  
    parent_ids = []  
    parents_data = [  
        {"email": "dad@example.com", "username": "Dad", "password": "password123"},  
        {"email": "mom@example.com", "username": "Mom", "password": "password123"}  
    ]  
  
    # Step 2: Insert Parent Users  
    for parent_info in parents_data:  
        hashed_password = bcrypt.generate_password_hash(parent_info["password"]).decode('utf-8')  
        parent_doc = {  
            'email': parent_info["email"],  
            'username': parent_info["username"],  
            'password_hash': hashed_password,  
            'role': 'parent',  
            'family_id': family_id_str,  # Link to family doc ID as string  
            'points': 0,  
            'lifetime_points': 0  
        }  
        parent_id_obj = users_collection.insert_one(parent_doc).inserted_id  
        parent_ids.append(str(parent_id_obj))  
        print(f"👤 Parent created -> username: {parent_info['username']}")  
  
    # Update the family's parent_ids with these newly-created parent ObjectIds  
    families_collection.update_one(  
        {'_id': family_id_obj},  
        {'$set': {'parent_ids': [ObjectId(pid) for pid in parent_ids]}}  
    )  
    print(f"🏡 Family document updated with ID: {family_id_str}")  
  
    # Step 3: Insert Child Users  
    children_data = [  
        {  
            "username": "Leo",  
            "password": "password123",  
            "points": random.randint(120, 250),  
            "lifetime_points": random.randint(300, 500)  
        },  
        {  
            "username": "Mia",  
            "password": "password123",  
            "points": random.randint(200, 350),  
            "lifetime_points": random.randint(500, 800)  
        }  
    ]  
    child_ids = []  
    for child_info in children_data:  
        child_hash = bcrypt.generate_password_hash(child_info["password"]).decode('utf-8')  
        child_doc = {  
            'username': child_info["username"],  
            'password_hash': child_hash,  
            'role': 'child',  
            'family_id': family_id_str,  
            'points': child_info["points"],  
            'lifetime_points': child_info["lifetime_points"]  
        }  
        child_id_obj = users_collection.insert_one(child_doc).inserted_id  
        child_ids.append(str(child_id_obj))  
        print(f"👤 Child created -> username: {child_info['username']}")  
  
    return family_id_str, parent_ids, child_ids  
  
  
def create_famjam_plan_and_events(family_id, child_ids):  
    """  
    Creates an active FamJam plan and generates chores for the plan.  
    Some chores in the past  (marked completed/approved), some in the future.  
    """  
    print("\n--- 🗓️  Generating FamJam Plan & Chore History ---")  
    family_oid = ObjectId(family_id)  
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)  
    current_quarter = (today.month - 1) // 3 + 1  
    start_month = (current_quarter - 1) * 3 + 1  
    start_date = today.replace(month=start_month, day=1)  
    end_date = start_date + relativedelta(months=3) - timedelta(days=1)  
  
    sample_plan_data = {  
        "plan_name": f"Teamwork Makes the Dream Work (Q{current_quarter})",  
        "suggested_chores": [  
            {  
                "name": "Morning Kitchen Reset",  
                "description": "Unload dishwasher, wipe counters.",  
                "points": 15,  
                "type": "chore",  
                "recurrence": "daily"  
            },  
            {  
                "name": "Evening Pet Care",  
                "description": "Feed the pets and check their water.",  
                "points": 10,  
                "type": "chore",  
                "recurrence": "daily"  
            },  
            {  
                "name": "Tidy Your Bedroom",  
                "description": "Make bed, put away clothes/toys.",  
                "points": 10,  
                "type": "chore",  
                "recurrence": "daily"  
            },  
            {  
                "name": "Weekly Bathroom Clean",  
                "description": "Wipe sink, mirror, and toilet.",  
                "points": 40,  
                "type": "chore",  
                "recurrence": "weekly"  
            },  
            {  
                "name": "Recycling & Trash Duty",  
                "description": "Take all bins out for collection day.",  
                "points": 25,  
                "type": "chore",  
                "recurrence": "weekly"  
            },  
        ]  
    }  
  
    famjam_plans_collection.insert_one({  
        'plan_data': sample_plan_data,  
        'family_id': family_oid,  
        'status': 'active',  
        'start_date': start_date,  
        'end_date': end_date  
    })  
  
    child_cycler = itertools.cycle(child_ids)  
    events_to_insert = []  
  
    # Generate recurring chores for the plan  
    for chore in sample_plan_data["suggested_chores"]:  
        if chore['recurrence'] == 'daily':  
            delta = timedelta(days=1)  
        elif chore['recurrence'] == 'weekly':  
            delta = timedelta(weeks=1)  
        else:  
            continue  
  
        current_due_date = start_date  
        while current_due_date <= end_date:  
            doc = {  
                **chore,  
                'family_id': family_oid,  
                'assigned_to': next(child_cycler),  
                'due_date': current_due_date,  
                'source': 'FamJamPlan',  
                'source_type': 'generated'  
            }  
            # If it's in the past, mark some chores as completed or approved  
            if current_due_date < today:  
                doc['status'] = 'approved' if random.random() < 0.9 else 'completed'  
                doc['approved_at'] = (  
                    current_due_date + timedelta(hours=random.randint(2, 26))  
                )  
            else:  
                doc['status'] = 'assigned'  
            events_to_insert.append(doc)  
  
            current_due_date += delta  
  
    if events_to_insert:  
        events_collection.insert_many(events_to_insert)  
        print(f"✅ Inserted {len(events_to_insert)} FamJam plan chore events.")  
  
  
def create_ad_hoc_events_and_habits(family_id, child_ids):  
    """  
    Creates some additional manually added chores or habits.  
    """  
    print("\n--- 🧩 Generating Ad-hoc Chores & Habits ---")  
    family_oid = ObjectId(family_id)  
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)  
    events_to_insert = []  
  
    sample_habits = [  
        {  
            'name': 'Practice Instrument',  
            'description': 'Complete a 15-minute practice session.',  
            'points': 15,  
            'assigned_to': child_ids[0]  
        },  
        {  
            'name': 'Read for 20 Minutes',  
            'description': 'Read a book, not a screen!',  
            'points': 20,  
            'assigned_to': child_ids[1]  
        },  
    ]  
  
    for habit in sample_habits:  
        events_to_insert.append({  
            **habit,  
            'type': 'habit',  
            'family_id': family_oid,  
            'status': 'assigned',  
            'due_date': today - timedelta(days=60),  
            'streak': random.randint(3, 12),  
            'last_completed': today - timedelta(days=random.choice([1, 2]))  
        })  
  
    if events_to_insert:  
        events_collection.insert_many(events_to_insert)  
        print(f"✅ Inserted {len(events_to_insert)} ad-hoc habit events.")  
  
  
def create_rewards_and_transactions(family_id, child_ids_map):  
    """  
    Generates a history of reward requests and corresponding transactions.  
    """  
    print("\n--- 🎁 Generating Rewards & Transactions ---")  
    family_oid = ObjectId(family_id)  
    today = datetime.utcnow()  
    docs = []  
  
    sample_rewards = [  
        {'name': 'One Hour of Video Games', 'cost': 100},  
        {'name': 'New Book ($15 limit)', 'cost': 200},  
        {'name': 'Movie Night Choice', 'cost': 150},  
        {'name': 'Ice Cream Outing', 'cost': 250}  
    ]  
  
    for _ in range(8):  
        reward = random.choice(sample_rewards)  
        child_id = random.choice(list(child_ids_map.keys()))  
        status = random.choices(['approved', 'rejected', 'requested'],  
                                weights=[0.7, 0.15, 0.15], k=1)[0]  
        spent_at = today - timedelta(days=random.randint(0, NUM_DAYS_HISTORY))  
        resolved_at = (  
            spent_at + timedelta(hours=random.randint(4, 24))  
            if status != 'requested' else None  
        )  
  
        reward_id = ObjectId()  
        # Rewards collection  
        docs.append((  
            rewards_collection,  
            {  
                '_id': reward_id,  
                'name': reward['name'],  
                'points_cost': reward['cost'],  
                'family_id': family_oid,  
                'requested_by_id': child_id,  
                'status': status,  
                'resolved_at': resolved_at  
            }  
        ))  
        # Transactions collection  
        docs.append((  
            transactions_collection,  
            {  
                'reward_id': reward_id,  
                'family_id': family_oid,  
                'child_id': child_id,  
                'child_username': child_ids_map[child_id],  
                'reward_name': reward['name'],  
                'points_spent': reward['cost'],  
                'status': status if status != 'requested' else 'pending',  
                'spent_at': spent_at,  
                'resolved_at': resolved_at  
            }  
        ))  
  
    for collection, doc in docs:  
        collection.insert_one(doc)  
  
    print(f"✅ Inserted {len(docs)//2} sample rewards and transactions.")  
  
  
def create_mood_entries(family_id, child_ids):  
    """  
    Generates daily mood entries for each child for the past NUM_DAYS_HISTORY.  
    """  
    print("\n--- 😊 Generating Mood Entries ---")  
    family_oid = ObjectId(family_id)  
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)  
    moods_to_insert = []  
  
    for child_id in child_ids:  
        for day in range(NUM_DAYS_HISTORY):  
            current_date = today - timedelta(days=day)  
            for period in ['Morning', 'Afternoon', 'Evening']:  
                # ~75% chance to log a mood  
                if random.random() < 0.75:  
                    mood_choice = random.choices(  
                        MOOD_CONFIG['moods'],  
                        weights=[0.1, 0.2, 0.5, 0.2],  
                        k=1  
                    )[0]  
                    mood_note = (  
                        random.choice(mood_choice['notes'])  
                        if random.random() < 0.3  
                        else ""  
                    )  
                    moods_to_insert.append({  
                        'user_id': ObjectId(child_id),  
                        'family_id': family_oid,  
                        'date': current_date,  
                        'period': period,  
                        'mood_emoji': mood_choice['emoji'],  
                        'mood_score': mood_choice['score'],  
                        'note': mood_note  
                    })  
  
    if moods_to_insert:  
        moods_collection.insert_many(moods_to_insert)  
        print(f"✅ Inserted {len(moods_to_insert)} mood entries.")  
  
  
def create_challenges(family_id, parent_ids, child_ids_map):  
    """  
    Creates sample family challenges in different states (open, in-progress, approved).  
    """  
    print("\n--- 🏆 Generating Family Challenges ---")  
    parent_id_obj = ObjectId(random.choice(parent_ids))  
    child_ids = list(child_ids_map.keys())  
    family_oid = ObjectId(family_id)  
  
    challenges_to_insert = [  
        {  
            "family_id": family_oid,  
            "title": "Yard Work Champion",  
            "description": "Rake all leaves and bag them up.",  
            "points": 150,  
            "status": "open",  
            "created_by_id": parent_id_obj,  
            "created_at": datetime.utcnow() - timedelta(days=2)  
        },  
        {  
            "family_id": family_oid,  
            "title": "Kitchen Deep Clean",  
            "description": "Clean the microwave and organize one drawer.",  
            "points": 100,  
            "status": "in_progress",  
            "created_by_id": parent_id_obj,  
            "created_at": datetime.utcnow() - timedelta(days=5),  
            "claimed_by_id": ObjectId(child_ids[0]),  
            "claimed_at": datetime.utcnow() - timedelta(days=1)  
        },  
        {  
            "family_id": family_oid,  
            "title": "Car Wash Pro",  
            "description": "Wash and vacuum the family car.",  
            "points": 80,  
            "status": "approved",  
            "created_by_id": parent_id_obj,  
            "created_at": datetime.utcnow() - timedelta(days=10),  
            "claimed_by_id": ObjectId(child_ids[1]),  
            "claimed_at": datetime.utcnow() - timedelta(days=8),  
            "completed_at": datetime.utcnow() - timedelta(days=7),  
            "approved_at": datetime.utcnow() - timedelta(days=6)  
        },  
    ]  
  
    if challenges_to_insert:  
        challenges_collection.insert_many(challenges_to_insert)  
        print(f"✅ Inserted {len(challenges_to_insert)} sample challenges.")  
  
  
def create_personal_items_and_timers(family_id, all_user_ids):  
    """  
    Creates personal notes/todos for each user, plus a couple of family timers.  
    """  
    print("\n--- 📝 Generating Personal Items & Timers ---")  
    family_oid = ObjectId(family_id)  
  
    # Personal items for each user  
    for user_id in all_user_ids:  
        # Personal notes  
        for i in range(random.randint(1, 3)):  
            notes_collection.insert_one({  
                'user_id': ObjectId(user_id),  
                'content': f"Sample note #{i+1} for planning.",  
                'created_at': datetime.utcnow() - timedelta(days=i * 3)  
            })  
        # Personal to-dos  
        for i in range(random.randint(2, 4)):  
            personal_todos_collection.insert_one({  
                'user_id': ObjectId(user_id),  
                'title': f"Personal to-do #{i+1}",  
                'is_done': random.choice([True, False]),  
                'created_at': datetime.utcnow() - timedelta(days=i)  
            })  
  
    # Family timers (2 examples)  
    timers_collection.insert_many([  
        {  
            'name': "Family Vacation Countdown",  
            'end_date': datetime.utcnow() + timedelta(days=45),  
            'family_id': family_oid,  
            'created_by': ObjectId(random.choice(all_user_ids))  
        },  
        {  
            'name': "Grandma's Visit",  
            'end_date': datetime.utcnow() + timedelta(days=12),  
            'family_id': family_oid,  
            'created_by': ObjectId(random.choice(all_user_ids))  
        }  
    ])  
    print(f"✅ Inserted personal items and 2 family timers.")  
  
  
def create_direct_messages(family_id, parent_ids, child_ids_map):  
    """  
    Simulates a short conversation history between parents and children.  
    """  
    print("\n--- 💬 Generating Direct Messages ---")  
    messages_to_insert = []  
    family_oid = ObjectId(family_id)  
  
    # Grab parent records to retrieve their usernames  
    parent1_id_obj, parent2_id_obj = ObjectId(parent_ids[0]), ObjectId(parent_ids[1])  
    parent1_user = users_collection.find_one({'_id': parent1_id_obj})  
    parent2_user = users_collection.find_one({'_id': parent2_id_obj})  
  
    child1_id, child1_name = list(child_ids_map.items())[0]  
    child2_id, child2_name = list(child_ids_map.items())[1]  
  
    # Child1 -> both parents  
    for pid in [parent1_id_obj, parent2_id_obj]:  
        messages_to_insert.append({  
            "family_id": family_oid,  
            "sender_id": ObjectId(child1_id),  
            "sender_username": child1_name,  
            "recipient_id": pid,  
            "message_content": "I finished my reading for today!",  
            "sent_at": datetime.utcnow() - timedelta(days=1, hours=5),  
            "is_read": True  
        })  
  
    # Parent1 -> Child1 reply  
    messages_to_insert.append({  
        "family_id": family_oid,  
        "sender_id": parent1_id_obj,  
        "sender_username": parent1_user['username'],  
        "recipient_id": ObjectId(child1_id),  
        "message_content": "That's awesome, great job!",  
        "sent_at": datetime.utcnow() - timedelta(days=1, hours=4),  
        "is_read": True  
    })  
  
    # Child2 -> both parents (unread)  
    for pid in [parent1_id_obj, parent2_id_obj]:  
        messages_to_insert.append({  
            "family_id": family_oid,  
            "sender_id": ObjectId(child2_id),  
            "sender_username": child2_name,  
            "recipient_id": pid,  
            "message_content": "Can we order pizza for dinner on Friday?",  
            "sent_at": datetime.utcnow() - timedelta(hours=2),  
            "is_read": False  
        })  
  
    # Message between parents  
    messages_to_insert.append({  
        "family_id": family_oid,  
        "sender_id": parent2_id_obj,  
        "sender_username": parent2_user['username'],  
        "recipient_id": parent1_id_obj,  
        "message_content": "Did you see Mia's message about pizza? Sounds good to me.",  
        "sent_at": datetime.utcnow() - timedelta(minutes=30),  
        "is_read": False  
    })  
  
    if messages_to_insert:  
        direct_messages_collection.insert_many(messages_to_insert)  
        print(f"✅ Inserted {len(messages_to_insert)} sample direct messages.")  
  
  
###############################################################################  
# Main Seeding Routine  
###############################################################################  
def seed_database():  
    """  
    Main function orchestrating the entire database seeding process.  
    """  
    print(f"--- 🚀 Starting Database Seeding for '{DB_NAME}' ---")  
    confirm = input(f"⚠️  This will DELETE ALL DATA in '{DB_NAME}'. Type 'yes' to continue: ")  
    if confirm.lower() != 'yes':  
        print("\nSeeding cancelled by user.")  
        return  
  
    # 1. Clear all existing data  
    clear_collections()  
  
    # 2. Create family, parents, and children  
    family_id, parent_ids, child_ids = create_family_members()  
    # Build a child username map for references in transactions, messages, etc.  
    child_docs = list(users_collection.find({'_id': {'$in': [ObjectId(cid) for cid in child_ids]}}))  
    child_ids_map = {str(doc['_id']): doc['username'] for doc in child_docs}  
  
    # 3. Create core data  
    create_famjam_plan_and_events(family_id, child_ids)  
    create_ad_hoc_events_and_habits(family_id, child_ids)  
    create_rewards_and_transactions(family_id, child_ids_map)  
    create_mood_entries(family_id, child_ids)  
    create_challenges(family_id, parent_ids, child_ids_map)  
    create_personal_items_and_timers(family_id, parent_ids + child_ids)  
    create_direct_messages(family_id, parent_ids, child_ids_map)  
  
    print("\n--- 🎉 Database Seeding Complete! ---")  
    print("Sample logins:")  
    print("  • Parent 1: dad@example.com / password123")  
    print("  • Parent 2: mom@example.com / password123")  
    print("  • Child 1: Leo / password123")  
    print("  • Child 2: Mia / password123")  
  
  
if __name__ == '__main__':  
    seed_database()  