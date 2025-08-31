

async def process_large_file_streaming(event, user_id, new_name):
    """Processes large files without downloading them entirely"""
    
    original_msg = user_sessions[user_id]['message']
    
    # Reuse file_id without download
    await event.client.send_file(
        event.chat_id,
        original_msg.media,  # Use media directly
        caption=f"<code>{new_name}</code>",
        parse_mode='html',
        file_name=new_name,
        supports_streaming=True,
        force_document=True
    )
