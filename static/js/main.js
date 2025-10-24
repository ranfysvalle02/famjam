// --- ROLE-AWARE & GLOBAL VARIABLES ---
// These are defined in base.html BEFORE this script runs
// const USER_ROLE = '...';
// const currentUserId = '...';
// const FAMILY_MEMBERS = [...];
// const USER_DATA = {...};

// --- MODAL & UI HELPER FUNCTIONS ---
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.remove('hidden');

  // Use requestAnimationFrame to ensure the 'hidden' class is removed
  // before we add 'is-open' for the transition to trigger.
  requestAnimationFrame(() => {
    modal.classList.add('is-open', 'flex'); // Use flex for centering
    modal.classList.remove('hidden'); // Redundant but safe

    const items = modal.querySelectorAll('.modal-content-item');
    items.forEach((item, index) => {
        item.style.animationDelay = `${150 + index * 100}ms`;
    });

    // If the personal modal is being opened, fetch the messages
    if (modalId === 'personalStuffModal') {
        const messagesPanel = document.getElementById('messages-panel');
        if (messagesPanel && !messagesPanel.hasAttribute('data-loaded')) {
            fetchAndDisplayMessages();
        }
    }
  });
}
function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.remove('is-open');

  // Wait for the transition to finish before adding 'hidden'
  // 600ms matches the 0.6s transition in your CSS
  setTimeout(() => {
      modal.classList.add('hidden');
      modal.classList.remove('flex'); // Remove flex
  }, 600);
}

function openEditModal(childId, username) {
  const editModal = document.getElementById('edit-child-modal');
  if (!editModal) return;
  document.getElementById('edit-child-id').value = childId;
  document.getElementById('edit-username').value = username;
  const form = document.getElementById('edit-child-form');
  if (form) {
      form.action = `/child/edit/${childId}`;
  }
  openModal('edit-child-modal');
}

function openResetChildPasswordModal(childId, childUsername) {
  const resetModal = document.getElementById('reset-child-password-modal');
  if (!resetModal) return;
  const usernameSpan = document.getElementById('reset-child-username');
  if (usernameSpan) usernameSpan.innerText = childUsername;
  const form = document.getElementById('reset-child-password-form');
  if (form) {
    form.action = `/child/reset-password/${childId}`;
    form.reset(); // Clear password field from previous use
  }
  openModal('reset-child-password-modal');
}

function openEditTaskModal(taskJsonString) {
    // This function assumes a modal with id 'edit-task-modal' exists
    // on the page it's called from (e.g., the /manage_plan page).
    try {
        const task = JSON.parse(taskJsonString);
        const form = document.getElementById('edit-task-form');
        if (!form) {
            console.error("edit-task-modal form not found on this page.");
            return;
        }
        form.action = `/event/edit/${task._id}`;
        const nameInput = document.getElementById('edit-task-name');
        const descInput = document.getElementById('edit-task-description');
        const pointsInput = document.getElementById('edit-task-points');
        const dateInput = document.getElementById('edit-task-due-date');
        const assignedToSelect = document.getElementById('edit-task-assigned-to');

        if (nameInput) nameInput.value = task.name || '';
        if (descInput) descInput.value = task.description || '';
        if (pointsInput) pointsInput.value = task.points || '';
        
        if (dateInput && task.due_date) {
             const dateObj = new Date(task.due_date);
             // Get parts in UTC to avoid timezone shifts
             const year = dateObj.getUTCFullYear();
             const month = (dateObj.getUTCMonth() + 1).toString().padStart(2, '0');
             const day = dateObj.getUTCDate().toString().padStart(2, '0');
             dateInput.value = `${year}-${month}-${day}`;
        }
        if (assignedToSelect) assignedToSelect.value = task.assigned_to || '';

        openModal('edit-task-modal');
    } catch (e) {
        console.error("Error parsing task JSON or setting form values:", e);
        alert("Could not load task details for editing.");
    }
}


/**
 * Converts a UTC date string into a user-friendly "time ago" format.
 */
function timeAgo(dateString) {
    if (!dateString) return '';
    try {
        // Adjust for potential MongoDB date format {$date: timestamp}
        const timestamp = dateString.$date || dateString;
        const date = new Date(timestamp);
        if (isNaN(date)) throw new Error("Invalid date");

        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 60) return "Just now";
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        if (days < 7) return `${days}d ago`;
        
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    } catch (error) {
        console.error("Error formatting time ago:", error, "Input:", dateString);
        return 'a while ago'; // Fallback
    }
}


// --- MESSAGING FUNCTIONS ---
async function handleMessageSubmit(form) {
    if (!form) {
        console.error("Form element not found for message submit.");
        return;
    }
    const formData = new FormData(form);
    const submitButton = form.querySelector('button[type="submit"]');
    if (submitButton) submitButton.disabled = true;

    try {
        const response = await fetch(form.action, {
            method: 'POST',
            body: formData
        });
        if (!response.ok) throw new Error('Network response was not ok.');
        
        // Refresh message list *after* successful send
        await fetchAndDisplayMessages(); 
        
        form.reset();
        const textarea = form.querySelector('textarea');
        if (textarea) textarea.style.height = 'auto'; // Reset textarea height
        
        // Hide the main compose area after successful send
        if (form.id === 'parent-compose-form') {
            document.getElementById('compose-message-form-container')?.classList.add('hidden');
        }
    } catch (error) {
        console.error('Error sending message:', error);
        alert('Could not send message. Please try again.');
    } finally {
        if (submitButton) submitButton.disabled = false;
    }
}

/**
 * Fetches, groups, and renders all conversations for the current user.
 */
async function fetchAndDisplayMessages() {
    const container = document.getElementById('conversation-accordion-container');
    const messagesPanel = document.getElementById('messages-panel');
    if (!container || !messagesPanel) return;

    container.innerHTML = `<div class="text-center text-gray-500 dark:text-gray-400 p-8">Loading conversations...</div>`;
    try {
        const response = await fetch('/api/messages');
        if (!response.ok) throw new Error('Failed to fetch messages.');

        const messages = await response.json();
        messagesPanel.setAttribute('data-loaded', 'true'); // Mark as loaded
        container.innerHTML = ''; // Clear loading message

        if (!messages || messages.length === 0) {
            container.innerHTML = `<div class="text-center text-gray-500 dark:text-gray-400 p-8">No messages yet. Start a conversation!</div>`;
            return;
        }

        // Use currentUserId defined in base.html script block
        if (!currentUserId) {
            console.error("currentUserId not available");
            return;
        }

        const conversations = {};
        const userMap = {};

        // Populate userMap from FAMILY_MEMBERS global variable
        if (typeof FAMILY_MEMBERS !== 'undefined' && FAMILY_MEMBERS.length > 0) {
            FAMILY_MEMBERS.forEach(member => {
                 const memberId = member._id.$oid || member._id;
                 if (memberId) {
                     userMap[memberId] = member.username;
                 }
            });
        }
        // Ensure current user is in the map
        if (typeof USER_DATA !== 'undefined' && USER_DATA.username) {
             userMap[currentUserId] = USER_DATA.username;
        } else if (currentUserId) {
             userMap[currentUserId] = "Me"; // Fallback
        }


        messages.forEach(msg => {
            const senderId = msg.sender_id?.$oid || msg.sender_id;
            const recipientId = msg.recipient_id?.$oid || msg.recipient_id;

            let partnerId = null;
            if (senderId && recipientId) {
                 partnerId = senderId === currentUserId ? recipientId : senderId;
            } else {
                 console.warn("Message missing sender or recipient ID:", msg);
                 return; 
            }

            // Fallback: If partnerId is not in userMap, get username from message
            if (!userMap[partnerId]) {
                 if (partnerId === senderId && msg.sender_username) {
                     userMap[partnerId] = msg.sender_username;
                 } else if (partnerId === recipientId && msg.recipient_username) { 
                     userMap[partnerId] = msg.recipient_username;
                 } else {
                      userMap[partnerId] = 'Unknown User'; 
                 }
            }

            if (!conversations[partnerId]) {
                conversations[partnerId] = {
                    username: userMap[partnerId] || 'Family Member',
                    messages: [],
                    hasUnread: false
                };
            }
            conversations[partnerId].messages.push(msg);

            // Check if the message is unread AND was not sent by the current user
            if (!msg.is_read && senderId !== currentUserId) {
                conversations[partnerId].hasUnread = true;
            }
        });


        // Sort conversations by the timestamp of the last message (most recent first)
        const sortedPartnerIds = Object.keys(conversations).sort((a, b) => {
             const lastMsgA = conversations[a].messages[conversations[a].messages.length - 1];
             const lastMsgB = conversations[b].messages[conversations[b].messages.length - 1];
             const dateA = new Date(lastMsgA?.sent_at?.$date || 0);
             const dateB = new Date(lastMsgB?.sent_at?.$date || 0);
             return dateB - dateA; // Descending order
        });


        // Render sorted conversations
        sortedPartnerIds.forEach(partnerId => {
            const convo = conversations[partnerId];
            // Sort messages within the conversation chronologically
            convo.messages.sort((a, b) => new Date(a.sent_at?.$date || 0) - new Date(b.sent_at?.$date || 0));

            const replyFormAction = '/send_message';
            const recipientInput = `<input type="hidden" name="recipient_id" value="${partnerId}">`;
            const placeholder = `Reply to ${convo.username}...`;

            const accordionItem = document.createElement('div');
            accordionItem.className = 'border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden';
            accordionItem.innerHTML = `
                <h2 id="accordion-heading-${partnerId}">
                    <button type="button" class="flex items-center justify-between w-full p-4 font-medium text-left text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 transition focus:outline-none" data-accordion-target="#accordion-body-${partnerId}" aria-expanded="false" aria-controls="accordion-body-${partnerId}">
                        <span>Conversation with ${convo.username}</span>
                        <div class="flex items-center gap-2">
                            ${convo.hasUnread ? '<span class="px-2 py-0.5 text-xs font-semibold text-blue-800 bg-blue-100 dark:bg-blue-900 dark:text-blue-200 rounded-full">New</span>' : ''}
                            <svg data-accordion-icon class="w-3 h-3 rotate-180 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"></path></svg>
                        </div>
                    </button>
                </h2>
                <div id="accordion-body-${partnerId}" class="hidden p-4 border-t border-gray-200 dark:border-gray-700" aria-labelledby="accordion-heading-${partnerId}">
                    <div class="message-list space-y-4 max-h-72 overflow-y-auto custom-scrollbar pr-2 mb-4">
                        ${convo.messages.map(msg => {
                            const senderId = msg.sender_id?.$oid || msg.sender_id;
                            const isSentByCurrentUser = senderId === currentUserId;
                            const messageTime = timeAgo(msg.sent_at); 
                            return `
                            <div class="flex ${isSentByCurrentUser ? 'justify-end' : 'justify-start'}">
                                <div class="p-3 rounded-lg max-w-xs sm:max-w-sm md:max-w-md shadow ${isSentByCurrentUser ? 'bg-blue-500 text-white' : 'bg-white dark:bg-gray-600 text-gray-800 dark:text-gray-100'}">
                                    <p class="text-sm break-words">${msg.message_content}</p>
                                    <p class="text-xs mt-1 ${isSentByCurrentUser ? 'text-blue-100 text-right' : 'text-gray-500 dark:text-gray-400 text-left'}">${messageTime}</p>
                                </div>
                            </div>`;
                        }).join('')}
                    </div>
                    <form method="POST" action="${replyFormAction}" class="reply-form flex gap-2 items-start mt-4">
                        ${recipientInput}
                        <textarea name="message_content" rows="1" required class="flex-grow p-2 bg-white dark:bg-gray-700 rounded-lg border border-gray-300 dark:border-gray-600 focus:ring-blue-500 focus:border-blue-500 transition text-sm resize-none overflow-hidden" placeholder="${placeholder}" oninput="this.style.height = 'auto'; this.style.height = (this.scrollHeight) + 'px';"></textarea>
                        <button type="submit" class="p-2 w-10 h-10 bg-blue-600 text-white rounded-full hover:bg-blue-700 transition flex-shrink-0 flex items-center justify-center self-end mb-1">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" /></svg>
                        </button>
                    </form>
                </div>`;

            container.appendChild(accordionItem);

            // Add event listener for the button AFTER appending
             const button = accordionItem.querySelector('button[data-accordion-target]');
             const target = document.getElementById(button.getAttribute('data-accordion-target').substring(1));
             const icon = button.querySelector('[data-accordion-icon]');

             button.addEventListener('click', () => {
                 const isExpanded = button.getAttribute('aria-expanded') === 'true';
                 button.setAttribute('aria-expanded', !isExpanded);
                 target.classList.toggle('hidden');
                 icon.classList.toggle('rotate-180');

                 if (!isExpanded) {
                      const messageList = target.querySelector('.message-list');
                      setTimeout(() => {
                           messageList.scrollTop = messageList.scrollHeight;
                      }, 50);
                 }
             });

        });

        // Add submit listeners to all reply forms AFTER they are in the DOM
        container.querySelectorAll('.reply-form').forEach(form => {
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                handleMessageSubmit(form);
            });
        });


        // If user is child, they usually have only one convo, open it.
        if (USER_ROLE === 'child' && sortedPartnerIds.length === 1) {
             const firstButton = container.querySelector('button[data-accordion-target]');
             if (firstButton && firstButton.getAttribute('aria-expanded') === 'false') {
                 firstButton.click(); // Open the conversation
             }
        } 

        // --- Mark unread messages as read ---
        const unreadMessageIds = messages
            .filter(m => !m.is_read && (m.sender_id?.$oid || m.sender_id) !== currentUserId)
            .map(m => m._id?.$oid || m._id);

        if (unreadMessageIds.length > 0) {
            try {
                await fetch('/api/message/mark-read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message_ids: unreadMessageIds }),
                });
                // Update UI indicators immediately
                document.getElementById('modal-message-badge')?.classList.add('hidden');
                document.querySelector('button[title="My Personal Space"] span.bg-red-500')?.classList.add('hidden');

            } catch (readError) {
                console.error("Failed to mark messages as read:", readError);
            }
        }

    } catch (error) {
        console.error("Error fetching/displaying messages:", error);
        container.innerHTML = `<div class="text-center text-red-500 p-8">Error: Could not load messages. ${error.message}</div>`;
    }
}


// --- MAIN SCRIPT EXECUTION (Global Listeners) ---
document.addEventListener("DOMContentLoaded", function() {
    
    // --- Basic UI Setup ---
    const mobileMenuButton = document.getElementById("mobile-menu-button");
    if (mobileMenuButton) {
        mobileMenuButton.addEventListener("click", () => openModal('mobileMenu'));
    }

    // --- Family Modal Tabs ---
    const familyModal = document.getElementById('manageFamilyModal');
    if (familyModal) {
        const tabButtonsFamily = familyModal.querySelectorAll('.tab-btn-family');
        const tabPanelsFamily = familyModal.querySelectorAll('.tab-panel-family');

        tabButtonsFamily.forEach(button => {
            button.addEventListener('click', () => {
                const targetPanelId = button.getAttribute('data-tab');

                // Update button styles
                tabButtonsFamily.forEach(btn => {
                    const isActive = btn === button;
                    btn.classList.toggle('border-blue-500', isActive);
                    btn.classList.toggle('text-blue-600', isActive);
                    btn.classList.toggle('dark:text-blue-400', isActive);
                    btn.classList.toggle('border-transparent', !isActive);
                    btn.classList.toggle('text-gray-500', !isActive);
                    btn.classList.toggle('dark:text-gray-400', !isActive);
                    btn.classList.toggle('hover:text-gray-700', !isActive);
                    btn.classList.toggle('dark:hover:text-gray-200', !isActive);
                });

                // Show/hide panels
                tabPanelsFamily.forEach(panel => {
                    panel.classList.toggle('hidden', panel.id !== targetPanelId);
                });
            });
        });
         
         // Add Edit Child Modal (Dynamically injecting to ensure it's available)
         // This code assumes it hasn't been added elsewhere.
        if (!document.getElementById('edit-child-modal')) {
            const editChildModalHTML = `
                <div id="edit-child-modal" class="side-modal fixed inset-0 z-[90] flex items-center justify-center bg-black bg-opacity-60 hidden p-4">
                  <div class="modal-content bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md mx-auto">
                    <div class="flex justify-between items-center p-6 border-b border-gray-200 dark:border-gray-700">
                      <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">Edit Child Account</h3>
                      <button onclick="closeModal('edit-child-modal')" class="p-2 rounded-full text-gray-400 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                      </button>
                    </div>
                    <form id="edit-child-form" method="POST" action="">
                      <div class="p-6 space-y-4">
                        <input type="hidden" name="child_id" id="edit-child-id">
                        <div>
                          <label for="edit-username" class="block text-sm font-medium text-gray-700 dark:text-gray-200">Username</label>
                          <input type="text" name="username" id="edit-username" required class="mt-1 block w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 rounded-lg border border-gray-300 dark:border-gray-600">
                        </div>
                      </div>
                      <div class="p-6 pt-0 text-right">
                        <button type="submit" class="px-6 py-2 font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition">Save Changes</button>
                      </div>
                    </form>
                  </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', editChildModalHTML);
        }

        // Add Reset Child Password Modal
        if (!document.getElementById('reset-child-password-modal')) {
            const resetPasswordModalHTML = `
                <div id="reset-child-password-modal" class="side-modal fixed inset-0 z-[90] flex items-center justify-center bg-black bg-opacity-60 hidden p-4">
                  <div class="modal-content bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md mx-auto">
                    <div class="flex justify-between items-center p-6 border-b border-gray-200 dark:border-gray-700">
                      <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">Reset Password for <span id="reset-child-username"></span></h3>
                      <button onclick="closeModal('reset-child-password-modal')" class="p-2 rounded-full text-gray-400 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition">
                         <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                      </button>
                    </div>
                    <form id="reset-child-password-form" method="POST" action="">
                      <div class="p-6 space-y-4">
                        <div>
                          <label for="new-child-password" class="block text-sm font-medium text-gray-700 dark:text-gray-200">New Temporary Password</label>
                          <input type="password" name="new_password" id="new-child-password" required minlength="6" class="mt-1 block w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 rounded-lg border border-gray-300 dark:border-gray-600">
                           <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">Min 6 characters. The child should change this after logging in.</p>
                        </div>
                      </div>
                      <div class="p-6 pt-0 text-right">
                        <button type="submit" class="px-6 py-2 font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 transition">Reset Password</button>
                      </div>
                    </form>
                  </div>
                </div>`;
              document.body.insertAdjacentHTML('beforeend', resetPasswordModalHTML);
        }

        // Add Change Parent Password Modal
        if (!document.getElementById('change-parent-password-modal')) {
            const changeParentPasswordModalHTML = `
              <div id="change-parent-password-modal" class="side-modal fixed inset-0 z-[90] flex items-center justify-center bg-black bg-opacity-60 hidden p-4">
                <div class="modal-content bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md mx-auto">
                  <div class="flex justify-between items-center p-6 border-b border-gray-200 dark:border-gray-700">
                    <h3 class="text-xl font-bold text-gray-900 dark:text-gray-100">Change My Password</h3>
                    <button onclick="closeModal('change-parent-password-modal')" class="p-2 rounded-full text-gray-400 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition">
                      <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                    </button>
                  </div>
                  <form method="POST" action="/change-password">
                    <div class="p-6 space-y-4">
                      <div>
                        <label for="current-password" class="block text-sm font-medium text-gray-700 dark:text-gray-200">Current Password</label>
                        <input type="password" name="current_password" id="current-password" required class="mt-1 block w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 rounded-lg border border-gray-300 dark:border-gray-600">
                      </div>
                       <div>
                        <label for="new-password" class="block text-sm font-medium text-gray-700 dark:text-gray-200">New Password</label>
                        <input type="password" name="new_password" id="new-password" required minlength="8" class="mt-1 block w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 rounded-lg border border-gray-300 dark:border-gray-600">
                         <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">Min 8 characters.</p>
                      </div>
                      <div>
                        <label for="confirm-password" class="block text-sm font-medium text-gray-700 dark:text-gray-200">Confirm New Password</label>
                        <input type="password" name="confirm_password" id="confirm-password" required minlength="8" class="mt-1 block w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 rounded-lg border border-gray-300 dark:border-gray-600">
                      </div>
                    </div>
                    <div class="p-6 pt-0 text-right">
                      <button type="submit" class="px-6 py-2 font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition">Change Password</button>
                    </div>
                  </form>
                </div>
              </div>`;
           document.body.insertAdjacentHTML('beforeend', changeParentPasswordModalHTML);
        }
    } // end if(familyModal)


    // --- Particle Background ---
    const particleContainer = document.getElementById('particle-container');
    if (particleContainer) {
        const numParticles = 20;
        // Use colors that show up well on the dark background
        const darkColors = ['rgba(59, 130, 246, 0.3)', 'rgba(236, 72, 153, 0.3)', 'rgba(16, 185, 129, 0.3)', 'rgba(168, 85, 247, 0.3)', 'rgba(245, 158, 11, 0.3)'];
        for (let i = 0; i < numParticles; i++) {
            const p = document.createElement('div');
            p.className = 'particle';
            const size = Math.random() * 10 + 10;
            p.style.cssText = `width:${size}px; height:${size}px; left:${Math.random()*100}%; top:${Math.random()*100 + 100}vh; animation-duration:${Math.random()*20+20}s; animation-delay: ${Math.random() * -40}s; background-color:${darkColors[Math.floor(Math.random()*darkColors.length)]};`;
            particleContainer.appendChild(p);
        }
    }

    // --- Dark Mode Logic has been REMOVED ---
    
    // --- Personal Space Modal Tabs & Compose Logic ---
    const personalStuffModal = document.getElementById('personalStuffModal');
    if (personalStuffModal) {
        const tabButtons = personalStuffModal.querySelectorAll('.tab-btn');
        const tabPanels = personalStuffModal.querySelectorAll('.tab-panel');

        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const targetPanelId = button.getAttribute('data-tab');

                // Update button styles
                tabButtons.forEach(btn => {
                    const isActive = btn === button;
                    btn.classList.toggle('border-blue-500', isActive);
                    btn.classList.toggle('text-blue-600', isActive);
                    btn.classList.toggle('dark:text-blue-400', isActive);
                    btn.classList.toggle('border-transparent', !isActive);
                    btn.classList.toggle('text-gray-500', !isActive);
                    btn.classList.toggle('dark:text-gray-400', !isActive);
                    btn.classList.toggle('hover:text-gray-700', !isActive);
                    btn.classList.toggle('dark:hover:text-gray-200', !isActive);
                });

                // Show/hide panels
                tabPanels.forEach(panel => {
                    panel.classList.toggle('hidden', panel.id !== targetPanelId);
                });

                // Fetch messages only when the messages tab is clicked
                if (targetPanelId === 'messages-panel' && !document.getElementById('messages-panel').hasAttribute('data-loaded')) {
                    fetchAndDisplayMessages();
                }
            });
        });

        // Compose message toggle logic
        const composeBtn = document.getElementById('compose-message-btn');
        const cancelBtn = document.getElementById('cancel-compose-btn');
        const composeContainer = document.getElementById('compose-message-form-container');

        if (composeBtn && composeContainer && cancelBtn) {
            const toggleCompose = () => composeContainer.classList.toggle('hidden');
            composeBtn.addEventListener('click', toggleCompose);
            cancelBtn.addEventListener('click', toggleCompose);
        }

         // Handle main compose form submission
         const composeForm = document.getElementById('parent-compose-form');
         if (composeForm) {
             composeForm.addEventListener('submit', (e) => {
                 e.preventDefault();
                 handleMessageSubmit(composeForm);
             });
         }
    } // end personalStuffModal checks


    // --- Invite link copy --- (For register_parent page)
    const copyButton = document.getElementById('copy-button');
    if (copyButton) {
        copyButton.addEventListener('click', function() {
            const urlInput = document.getElementById('invite-url-input');
            const copyIcon = document.getElementById('copy-icon');
            const checkIcon = document.getElementById('check-icon');
            if (!urlInput || !copyIcon || !checkIcon) return;

            navigator.clipboard.writeText(urlInput.value).then(() => {
                copyIcon.classList.add('hidden');
                checkIcon.classList.remove('hidden');
                setTimeout(() => {
                    copyIcon.classList.remove('hidden');
                    checkIcon.classList.add('hidden');
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy text: ', err);
            });
        });
    }

    // --- Username suggestion --- (For registration pages)
    const suggestBtn = document.getElementById('suggest-username-btn');
    if (suggestBtn) {
        const usernameInput = document.getElementById('username');
        const suggestionsContainer = document.getElementById('username-suggestions');
        const isParentRegistration = document.querySelector('form[action*="register_parent"]') !== null;

        if (usernameInput && suggestionsContainer) {
            suggestBtn.addEventListener('click', async () => {
                const originalBtnText = suggestBtn.textContent;
                suggestBtn.innerHTML = '<span class="animate-pulse">Thinking...</span>';
                suggestBtn.disabled = true;
                suggestionsContainer.innerHTML = ''; 

                const nameSeed = (isParentRegistration && usernameInput.value.trim()) ? usernameInput.value.trim() : '';

                try {
                    const response = await fetch('/api/suggest-username', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: nameSeed })
                    });
                    if (!response.ok) {
                         const errorData = await response.json().catch(() => ({}));
                         throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                    }
                    const data = await response.json();

                    if (data.suggestions && data.suggestions.length > 0) {
                        data.suggestions.forEach(suggestion => {
                            const suggBtn = document.createElement('button');
                            suggBtn.type = 'button';
                            suggBtn.textContent = suggestion;
                            suggBtn.className = 'px-3 py-1 text-sm text-blue-700 bg-blue-100 rounded-full hover:bg-blue-200 dark:bg-blue-900 dark:text-blue-200 dark:hover:bg-blue-800 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-300';
                            suggBtn.onclick = () => {
                                usernameInput.value = suggestion;
                                suggestionsContainer.innerHTML = '';
                                usernameInput.focus();
                            };
                            suggestionsContainer.appendChild(suggBtn);
                        });
                    } else {
                        suggestionsContainer.innerHTML = '<p class="text-sm text-gray-500 dark:text-gray-400">No suggestions found. Try again.</p>';
                    }
                } catch (error) {
                    console.error('Error fetching username suggestions:', error);
                    suggestionsContainer.innerHTML = `<p class="text-sm text-red-500 dark:text-red-400">Could not load suggestions: ${error.message}</p>`;
                } finally {
                    suggestBtn.textContent = originalBtnText;
                    suggestBtn.disabled = false;
                }
            });
        }
    } // end suggestBtn check

}); // End DOMContentLoaded