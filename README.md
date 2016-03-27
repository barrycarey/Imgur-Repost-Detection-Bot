**Imgur Repost Detection Bot**
------------------------------

This Python script acts as an Imgur bot that detects reposted content.

While running it pulls all new images from Usersub, calculates a hash (using Dhash for 16, 64, and 256bit hashes), stores it in a MySQL Database.  

All hashes for new images are added to a queue.  This queue is handled via a process pool.  The amount of processes is configurable via the ini.

![alt text](http://puu.sh/nW3mr/ed03d7d601.png "Screenshot")

**How Does It Detect Reposted Content?**

For each image a hash is generated using the Dhash algorithm and stored in the database.

We can then check the hash of new images against existing hashes using hamming distance. If the hamming distance is less than the threshold set in the config it is flagged as a repost.

**Configuration**

In the bot.ini enter your Imgur API details along with your MySQL details.

A template MySQL file can be found in the sql folder.

Once ready run ImgurRepostBot.py

**Notable Features**

 - Automatic API rate limiting.  It continually checks your remaining credits and the time until they reset.  It then adjusts the request delay to fit within that time. 
 - Backfill Database.  This allows the bot to work backwards through usersub pages while still getting the newest images.  This allows you to backfill your database
 - Configurable hash size and hamming distance allows you to tweak the accuracy of repost detections. 
 - Enable / Disable Automatic Downvote and Comment via bot.ini
 - Modify settings in the .ini file while the bot is running
 - Auto Retry failed comments and downvotes.  If Imgur is over capacity they will be saved and tried again later

**Comment Template Usage**

You can specify a custom comment template via the bot.ini file.  This allows you to use {} as place holders for values in the comment. 

You then pass a list of the values into comment_repost(values=values).  It will format the comment based on your template and the list of values you pass in. 

Example Comment Template:  Detected Reposted Image with ID {} and Hash {}

Example Values:  ['s78sdfy', '31b132726521b372]

**Required Libraries**

 - <a href="http://www.sqlalchemy.org/" target="_blank">Sqlalchemy</a>
 - <a href="https://github.com/Imgur/imgurpython" target="_blank">imgurpython</a>
 - <a href="https://python-pillow.github.io/" target="_blank">Pillow</a>
 - <a href="https://github.com/PyMySQL/PyMySQL/" target="_blank">PyMysql</a>
 - <a href="https://pypi.python.org/pypi/Distance/" target="_blank">Distance</a>

**Disclaimer**

This is a WIP: I'm still adding stuff and messing around with it

I'm not a professional programmer, more of a hobbyist. Due to this the code may not be the cleanest.  I welcome suggestions and pull requests.

I made this bot as coding practice.

I'm aware the functionality is similar to the [RepostStatistics](http://imgur.com/user/RepostStatistics).

**Use At Your Own Risk**	