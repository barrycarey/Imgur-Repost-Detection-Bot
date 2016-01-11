**Imgur Repost Detection Bot**
------------------------------

This Python script acts as an Imgur bot that detects reposted content.

While running it pulls all new images from Usersub, calculates a hash (using Dhash), stores it in a MySQL Database.  The image hash is set aside to be checked in batches.

Every 30 seconds (configurable via bot.ini) it will take the accumulated hashes and check them against the database.  If we find reposted content the bot can downvote and/or leave a comment.  This behavior can be modified in the bot.ini file.

**How Does It Detect Reposted Content?**

For each image a hash is generated using the Dhash algorithm and stored in the database.

We can then check the hash of new images against existing hashes using hamming distance. If the hamming distance is found to be less than 2 it is treated as reposted content.

**Configuration**

In the bot.ini enter your Imgur API details along with your MySQL details.

A template MySQL file can be found in the sql folder.

Once ready run ImgurRepostBot.py

**Notable Features**

 - Custom Comment Templates Using {} As Value Placeholders
 - Enable / Disable Automatic Downvote and Comment via bot.ini
 - Modify settings in the .ini file while the bot is running
 - Auto Retry failed comments and downvotes.  If Imgur is over capacity they will be saved and tried again later

**Comment Template Usage**

You can specify a custom comment template via the bot.ini file.  This allows you to use {} as place holders for values in the comment. 

You then pass a list of the values into comment_repost(values=values).  It will format the comment based on your template and the list of values you pass in. 

Example Comment Template:  Detected Reposted Image with ID {} and Hash {}

Example Values:  ['s78sdfy', '31b132726521b372]

**Required Libraries**

 - Sqlalchemy
 - imgurpython
 - Pillow
 - PyMysql

**Disclaimer**

This is a WIP: I'm still adding stuff and messing around with it

I'm not a professional programmer, more of a hobbyist. Due to this the code may not be the cleanest.  I welcome suggestions and pull requests.

I made this bot as coding practice.

I'm aware the functionality is similar to the [RepostStatistics](http://imgur.com/user/RepostStatistics).

**Use At Your Own Risk**