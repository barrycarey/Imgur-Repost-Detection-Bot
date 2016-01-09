**Imgur Repost Detection Bot**
------------------------------

This Python script acts as an Imgur bot that detects reposted content.

While running it pulls all new images from Usersub, calculates a hash (using Dhash), stores it in a MySQL Database.  The image hash is set aside to be checked in batches.

Every 30 seconds it will take the accumulated hashes and check them against the database.  If we find reposted content the bot can downvote and/or leave a comment.  This behavior can be modified in the bot.ini file.

**How Does It Detect Reposted Content?**

For each image a hash is generated using the Dhash algorithm and stored in the database.

We can then check the hash of new images against existing hashes using hamming distance. If the hamming distance is found to be less than 2 it is treated as reposted content.

**Configuration**

In the bot.ini enter your Imgur API details along with your MySQL details.

A template MySQL file can be found in the sql folder.

Once ready run ImgurRepostBot.py

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