

async def process_large_file_streaming(event, user_id, new_name):
    """Traite les gros fichiers sans les télécharger entièrement"""
    
    original_msg = user_sessions[user_id]['message']
    
    # Réutiliser le file_id sans téléchargement
    await event.client.send_file(
        event.chat_id,
        original_msg.media,  # Utilise directement le media
        caption=f"<code>{new_name}</code>",
        parse_mode='html',
        file_name=new_name,
        supports_streaming=True,
        force_document=True
    )
