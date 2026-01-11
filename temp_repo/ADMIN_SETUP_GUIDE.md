# Admin Commands Setup Guide

## Overview
Your bot now has a complete admin system that allows certain users to have special privileges and commands.

## How It Works

### 1. Admin Authentication
- Admin users are identified by their Telegram user ID
- IDs are stored in the `ADMIN_IDS` environment variable
- Multiple admins can be added by separating IDs with commas

### 2. Setting Up Admins

#### Step 1: Get Your Telegram User ID
You have two options:
- **Option A**: Message [@userinfobot](https://t.me/userinfobot) on Telegram
- **Option B**: Use `/admin` command in your bot (it will tell you if you're an admin or not)

#### Step 2: Add Admin IDs to Replit Secrets
1. Click on "Secrets" in the left sidebar (the lock icon 🔒)
2. Add a new secret:
   - Key: `ADMIN_IDS`
   - Value: Your user ID (e.g., `123456789`)
3. For multiple admins: `123456789,987654321,555555555`

#### Step 3: Restart Your Bot
The bot reads admin IDs when it starts, so you need to restart it to apply changes.

## Available Admin Commands

### `/admin`
Check if you're an admin and see all available admin commands.

**Example:**
```
/admin
```

### `/givebal <user_id> <amount>`
Give money to any user.

**Example:**
```
/givebal 123456789 100
```
This gives $100 to user ID 123456789.

### `/setbal <user_id> <amount>`
Set a user's balance to a specific amount (replaces their current balance).

**Example:**
```
/setbal 123456789 500
```
This sets user ID 123456789's balance to exactly $500.

### `/allusers`
View all registered users (shows up to 50 users with their ID, username, and balance).

**Example:**
```
/allusers
```

### `/userinfo <user_id>`
View detailed information about a specific user including stats, balance, and referral info.

**Example:**
```
/userinfo 123456789
```

### `/backup`
Download the entire database as a JSON file for backup purposes.

**Example:**
```
/backup
```

## Security Notes

- **Keep admin IDs private**: Anyone with an admin ID can control user balances
- **Regular users cannot see or use admin commands**: They'll get an error message
- **All admin actions are logged**: Check the bot console for admin activity
- **Transactions are tracked**: Admin gives/sets are recorded in the user's transaction history

## Troubleshooting

### "You are not an admin" message
- Verify your user ID is correct
- Check that `ADMIN_IDS` secret is properly set in Replit
- Make sure there are no spaces in the comma-separated list
- Restart the bot after adding admin IDs

### Commands not working
- Make sure you're using the correct format (check examples above)
- User IDs must be numeric
- Amounts must be valid numbers (can include decimals like 10.50)

## Examples

### Adding yourself as an admin:
1. Message @userinfobot - let's say it replies with `123456789`
2. Add secret in Replit: `ADMIN_IDS=123456789`
3. Restart the bot
4. Send `/admin` to your bot - you should see admin menu

### Adding multiple admins:
```
ADMIN_IDS=123456789,987654321,555555555
```

### Giving a user $50:
```
/givebal 123456789 50
```

### Setting a user's balance to $1000:
```
/setbal 123456789 1000
```

### Viewing user details:
```
/userinfo 123456789
```
