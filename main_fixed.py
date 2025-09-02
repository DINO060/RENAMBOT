#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ... (le reste du code reste inchangé jusqu'à la fonction message_handler)

@bot.on(events.NewMessage())
async def message_handler(event):
    # Only handle private messages
    if not event.is_private:
        return
    
    user_id = event.sender_id
    
    # Check if user is in a session awaiting custom text
    if user_id in sessions and sessions[user_id].get('awaiting_custom_text'):
        # Remove the awaiting flag
        sessions[user_id].pop('awaiting_custom_text', None)
        
        # Check if this is a cancel command
        if event.raw_text.strip().lower() == '/cancel':
            await event.reply("❌ Custom text addition cancelled.", parse_mode='html')
            await show_settings_menu(event)
            return
            
        # Save the custom text
        custom_text = event.raw_text.strip()
        if user_id not in sessions:
            sessions[user_id] = {}
        sessions[user_id]['custom_text'] = custom_text
        save_user_preferences()
        
        # Confirm and show settings menu
        await event.reply(f"✅ Custom text set to: <code>{custom_text}</code>", parse_mode='html')
        await show_settings_menu(event)
        return
    
    # If we get here, it's a regular message that doesn't require special handling
    # Just return to avoid processing further
    return

# ... (le reste du code reste inchangé)
