# 🎯 Limits System and Automatic Cleanup

## 📊 Usage Limits

### Daily Limit
- **1 GB per day** per user
- Automatic reset at midnight (00:00)
- Real-time usage tracking

### Delay Between Files
- **30 seconds** cooldown between each file
- Prevents spam and protects resources

## 🔧 New Commands

### `/usage`
Displays user usage statistics:
- Current daily usage
- Remaining limit
- Visual progress bar
- Next reset

### `/cleanup` (Admin only)
Cleans all user files:
- Removes temporary files
- Preserves thumbnails
- Session cleanup

## 🗂️ File Management

### Automatic Cleanup
- **Every hour**: Orphaned file cleanup
- **After each 1GB**: Silent user file cleanup
- **Expired sessions**: Automatic cleanup after 10 minutes

### Preserved Files
- ✅ Custom thumbnails
- ✅ Usage data
- ✅ Active sessions

### Deleted Files
- ❌ Orphaned temporary files (>1 hour)
- ❌ Expired sessions
- ❌ Completed processing files

## 📈 Usage Tracking

### Storage
- Data saved in `user_usage.json`
- Persistence between restarts
- Readable JSON format

### Metrics
- Total size used per day
- Number of files processed
- Last activity
- Reset history

## 🛡️ Security

### Abuse Protection
- Rate limiting per user
- Limit verification before processing
- Informative error messages

### Error Handling
- Detailed operation logging
- Automatic error recovery
- Cleanup on crash

## ⚙️ Configuration

### Modifiable Variables
```python
DAILY_LIMIT_GB = 1  # Daily limit in GB
COOLDOWN_SECONDS = 30  # Delay between files
USER_TIMEOUT = 600  # Session timeout (10 min)
```

### Data Files
- `user_usage.json` : Usage data
- `temp_files/` : Temporary files
- `thumbnails/` : User thumbnails

## 🚀 Usage

1. **File upload**: Automatic limit verification
2. **Processing**: Usage update after success
3. **Cleanup**: Automatic temporary file removal
4. **Tracking**: `/usage` command to check limits

## 📝 Logs

The system generates detailed logs:
- Usage updates
- Automatic cleanup
- Limit errors
- File deletion

## 🔄 Maintenance

### Manual Cleanup
```bash
# Remove all temporary files
rm -rf temp_files/*

# Remove usage data
rm user_usage.json
```

### Monitoring
- Check disk space
- Monitor error logs
- Control usage per user 