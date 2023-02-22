"""
Phlashcards
Chris Luginbuhl

Phlashcards is a web app is intended for learning & remembering anything - language, facts, stories, people's names...

It uses training frequency inspired by the Pimsleur language courses to ask you things just before you're about to
forget them, e.g. after 5 minutes, after 20 minutes, after an hour, after 1 day, 3, days, etc.
The newest flash cards are shown with the greatest frequency.

It is intended to be deployed using Airtable (for db), Firebase (for images) and Python Anywhere
(now that Heroku/Postgres is not free!)
The app also supports multiple users in the same database.

Makes use of some code from Udemy/App Brewery's 100 Days of Code day 64 and 69 for user registration, login, etc.

Uses Python, Javascript, Flask for rendering html, jinja for variables, flask-wtf for forms, pyairtable for database.
"""

import os
import global_constants as gc
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_bootstrap import Bootstrap
from flask_ckeditor import CKEditor
import datetime as dt
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, login_user, LoginManager, login_required, current_user, logout_user
from forms import CreateCardForm, RegisterForm, LoginForm, SkipCardForm
from secrets import token_hex
from functools import wraps
import math
import random
from collections import namedtuple
from pyairtable import Api, Base, Table
from pyairtable.formulas import match
from flask_debugtoolbar import DebugToolbarExtension
from bleach import clean
import requests
from requests.exceptions import MissingSchema, ConnectionError
import json
from loguru import logger


# Run Pydoc window with: python -m pydoc -p <port_number>

# TODO 1: Check all routes on debug toolbar "routes" e.g. /ckeditor/static/<path:filename> for login_required
# TODO 2: * Allow uploading images to Firebase or similar for permanent URL
# TODO 3: HOLD: implement tags. Possibly using this: https://larainfo.com/blogs/bootstrap-5-tags-input-examples
#             or this https://stackoverflow.com/questions/63702099/how-to-make-a-checkbox-checked-in-jinja2
#             see this: https://github.com/yairEO/tagify#features under "Build Project"
# TODO 4: ---COMPLETED--- implement tag filters
# TODO  : HOLD: card layout for tags
# TODO 5: ---COMPLETED----Implement 'skip for today'
# TODO 6: ---COMPLETED----Different decay rates?
# TODO 7: ---COMPLETED----check if max infrequency works, i.e. what happens after 20 views
# TODO 8: Swipe for navigation on mobile? https://demo.dsheiko.com/spn/
# TODO 9: ---COMPLETED---Implement Delete Card (or Archive Card)
# TODO 10: Decide what to do with /index. Starred cards? Tags? Oldest/newest/random?
# TODO 11: ---COMPLETED---Implement frequency decay rate
# TODO 12: ---COMPLETED---Connect DB tables (author name and ID) -> maybe not? THis makes updating fields a PITA
# TODO 13: Launch 1.0 on PAnywhere
# TODO 14: HOLD Preload body and img for all cards in queue rather than retrieving one at at time
# TODO 15: ---COMPLETED--- Card layout (buttons always at top and bottom?)
# TODO 16: ---COMPLETED--- Implement 'skip for x days' input
# TODO 17: ---COMPLETED---Simplify input form: fill default values for frequency decay etc
# TODO 18: ---COMPLETED---Make images (and various other fields?) optional
# TODO 19: Dark mode: https://github.com/vinorodrigues/bootstrap-dark-5
# TODO 20: HOLD Implement offline mode from local db? Read only, but refreshed on initial fill_queue?
# TODO 21: HOLD Implement multiple page cards/series? Bootstrap carousel?

card_datafield_names = ['rec_id', 'card_id', 'num_views', 'initial_frequency', 'frequency_decay', 'weight',
                                'tags', 'skip_until', 'archived', 'date_created', 'title', 'body', 'author', 'img_url']
Card_data = namedtuple('Card_data', card_datafield_names)

cache_file = 'cache.json'

Flask.secret_key = token_hex(16)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('APP_SECRET_KEY')
ckeditor = CKEditor(app)
Bootstrap(app)

app.debug = True  # This is for debug toolbar
app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = False
toolbar = DebugToolbarExtension(app)

# logger.add("file_{time}.log", rotation="10 MB")

## CONNECT TO AIRTABLE AS DB
airtable_api_key = os.environ.get('AIRTABLE_API_KEY')
airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')

airtable_cards_table_name = 'cards_table'
airtable_user_table_name = 'users_table'
api = Api(airtable_api_key)
card_table = Table(airtable_api_key, airtable_base_id, airtable_cards_table_name)
user_table = Table(airtable_api_key, airtable_base_id, airtable_user_table_name)
login_manager = LoginManager()
login_manager.init_app(app)


class User(UserMixin):
    def __init__(self, user_name, email, password_hash, id=0, ):
        self.id = id
        self.user_name = user_name
        self.email = email
        self.password_hash = password_hash


class Schedule:
    """Creates a queue of cards and serves the next card"""

    # Creates a queue of card_ids according to these rules:
    # Pick QUEUE_SIZE cards randomly, according to weights
    # No duplicates in queue. Add new cards to end, remove from start in batches of QUEUE_SIZE/2.
    # Batches prevent frequent db calls, and having a queue larger than the batch prevents getting
    # the same card twice in a row (or more than once in QUEUE_SIZE/2 cards)
    # Don't add cards to queue if they are marked "skip for today"
    # returns the database id of the next card. This is a weighted random choice. Weights are calculated from the
    # initial_frequency, num_views (in db) and the weights that decrease with increasing number of views.
    #
    # Get all card info:
    # * Note - you must have a number of cards in database >= QUEUE_SIZE
    # 1. Get all rec_id, card_id, initial_frequency, num_views, skip_for_today etc from
    #      database (don't need to load title, images, body, etc)
    # 2. Calculate weights (initial_frequency * exponential decay according to num views)
    #
    # Refresh queue:
    # 3. Create a list of eligible cards (cards not in the queue already, not skip for today, etc.)
    # 4. Pick a card from eligible cards list randomly, add it to the end of the queue, remove it from eligible cards
    #    list
    # 5. repeat step 4 until queue is full
    # 6. Method get_next_card(): Keep an index, and serve this card_id from the queue when asked.
    # 7. When index reaches end of queue, update num_views (and "do not show today") in db for all cards in queue
    #   (Option to implement: Also do 7a) if/when no new card for 2 minutes)
    # 8. Update eligible cards from db (removing everything in queue)
    # 9. Clear the queue
    # 10.GOTO step 4 (heh)
    #
    # Summary:
    # fill queue with eligible cards, removing them one at a time from eligible cards list
    # serve cards til end of queue
    # update num_views (and "do not show today") in db
    # update eligible cards from db (removing everything in queue)
    # fill queue from eligible cards

    def __init__(self):
        self.index = -1
        self.queue = []
        self.eligible_cards = []
        self.excluded_tags = ['Language']

    @logger.catch()
    def fill_queue(self):
        """Retrieves selected fields for all db records, calculates weights, makes list of eligible cards, fills queue"""
        try:
            card_data_raw = card_table.all(fields=['card_id', 'num_views', 'initial_frequency', 'frequency_decay', 'tags',
                                               'skip_until', 'archived'])
            card_data = [add_missing(card) for card in card_data_raw]
            logger.debug(f'Retrieved Card_data from db: {len(card_data)} items. First item: {card_data[0]}')
        except ConnectionError:
            logger.error("Connection Error: Unable to reach database.")
            flash("Connection Error: Unable to reach database.")
            # TODO: Load cached data
            # card_data = read_cache()
        #Unpack json into a bunch of lists.
        rec_ids = [card['rec_id'] for card in card_data]
        card_ids = [card['card_id'] for card in card_data]
        num_views = [card['num_views'] for card in card_data]
        frequency_decay = [card['frequency_decay'] for card in card_data]
        initial_frequencies = [card['initial_frequency'] if 'initial_frequency' in card.keys() else gc.INITIAL_FREQUENCY_DEFAULT for card in card_data]
        # TODO ^v Move this default handling elsewhere
        tags = [card['tags'] if 'tags' in card.keys() else '' for card in card_data]
        skip_until = [card['skip_until'] if 'skip_until' in card.keys() else gc.SKIP_UNTIL_DATE_DEFAULT for card
                      in card_data]
        archived = [card['archived'] if 'archived' in card.keys() else False for card in card_data]
        weights = [get_weight(init_freq, num_views[idx], frequency_decay[idx]) for idx, init_freq in
                   enumerate(initial_frequencies)]

        all_cards = [
            Card_data(rec_ids[idx], card_id, num_views[idx], initial_frequencies[idx], frequency_decay[idx],
                      weights[idx],
                      tags[idx], skip_until[idx], archived[idx], None, None, None, None, None) for idx, card_id in
            enumerate(card_ids)]
        # ^ The None values are for title, date_created, body, author and img_url which are not loaded here to save memory
        # ^ List comp of named tuples "Card_data"
        logger.debug(f'Loaded all cards. First one: {all_cards[0]}')
        today = dt.date.today()
        ids_of_cards_in_queue = [card.card_id for card in self.queue]
        self.eligible_cards = [
            card for card in all_cards if
            card.card_id not in ids_of_cards_in_queue and not
            card.archived and
            (dt.datetime.strptime(card.skip_until, '%Y-%m-%d').date() - today) < dt.timedelta(days=1) and not
            (not card.tags or set(card.tags.split(' ')).intersection(set(self.excluded_tags)))
            # last condition above ^ is: if there are tags, split them up and check if they're excluded
        ]
        logger.info(f'Queue is: {[card.card_id for card in self.queue]}')
        logger.info(f'Eligible cards are: {sorted([card.card_id for card in self.eligible_cards])}')
        # Now fill the queue
        # self.queue = []
        self.queue.clear()
        for i in range(gc.QUEUE_SIZE):
            try:
                self.queue.append(random.choices(self.eligible_cards,
                                                 [card.weight for card in self.eligible_cards], k=1)[0])
                self.eligible_cards.pop(self.eligible_cards.index(self.queue[-1]))
                # remove last added card from eligible
            except:
                logger.error(
                    f'An error occurred while filling the queue. Possibly not enough cards to fill '
                    f'queue of {gc.QUEUE_SIZE}')
        logger.info(f'queue is: {[card.card_id for card in self.queue]}')

    @logger.catch()
    def get_next_card(self) -> Card_data:
        if not self.queue:  # Queue is empty when the app first opens
            self.fill_queue()

        self.index += 1
        if self.index == gc.QUEUE_SIZE:
            self.update_db()
            self.fill_queue()
            self.index = 0
        next_card = self.queue[self.index]
        logger.info(f'Next card: {next_card.card_id}. '
                    f'Num_views: {next_card.num_views}, '
                    f'Init_freq: {next_card.initial_frequency}, '
                    f'Decay rate: {next_card.frequency_decay}, '
                    f'Weight: {next_card.weight}, '
                    f'Tags: {next_card.tags}')
        return next_card

    @logger.catch()
    def skip_card(self, card_id: int, days_to_skip: int):

        # TODO Next: Modify this function to find card in db, not in queue, commit change right away

        try:
            queue_position = [i for i, card in enumerate(self.queue) if card.card_id == card_id][0]
            logger.debug(f'Found card to skip in queue position {queue_position}')
            self.queue[queue_position] = self.queue[queue_position]._replace(skip_until=str(dt.date.today() +
                                                                                dt.timedelta(days=days_to_skip)))
            logger.debug(
                f"Changed card {card_id}'s skip until to {str(dt.date.today() + dt.timedelta(days=days_to_skip))}")
            # ^ named tuples are immutable so must replace the whole tuple
        except IndexError:
            logger.error(f'Index Error while skipping card {card_id}. Not skipping.')

    def update_db(self):
        updates_list = [{'id': card.rec_id, "fields": {"num_views": card.num_views + 1, "skip_until": card.skip_until}}
                        for card in self.queue]
        logger.debug(f'Updates list: {updates_list}')
        try:
            card_table.batch_update(updates_list)
        except ConnectionError:
            logger.error("Connection Error: Unable to reach database.")

# HELPER FUNCTIONS
@logger.catch()
def check_is_url_image(image_url):
    image_formats = ("image/png", "image/jpeg", "image/jpg")
    # TODO: Add/test GIF to image formats ^
    if image_url:
        try:
            r = requests.head(image_url)
            if r.headers["content-type"] in image_formats:
                return image_url
            else:
                flash(f'URL does not link to an image of type {"".join(image_formats)}')
                logger.error(f'URL does not link to an image of type {"".join(image_formats)}')
                return gc.BROKEN_LINK_IMG_URL
        except ConnectionError:
            logger.error(f'Connection Error: {image_url} ')
        except MissingSchema:
            flash(f'Image URL is not complete. (May need https://). URL is {image_url}')
            logger.error(f'URL is not complete (may need "https://"). URL is {image_url}')
    else:
        logger.info('Image URL is empty.')
    # return gc.BROKEN_LINK_IMG_URL
    return None


@logger.catch()
def sanitize(raw_title, raw_body, raw_img_url):
    """uses library bleach to remove html tags (including malicious scripts) and performs other checks on form input
    There are no checks within db or on output."""
    img_url = ''
    # body = clean(raw_body, tags=['em', 'i', 'br'], strip=True)
    body = clean(raw_body, tags=['em', 'p', 'br', 'i'], strip=True)
    title = clean(raw_title, strip=True)
    if raw_img_url:
        img_url = check_is_url_image(raw_img_url)
    return title, body, img_url


@logger.catch()
def default_if_none(freq_decay=gc.FREQUENCY_DECAY_DEFAULT, n_views=0,
                    init_freq=gc.INITIAL_FREQUENCY_DEFAULT,
                    s_until=dt.datetime.strptime(gc.SKIP_UNTIL_DATE_DEFAULT, '%Y-%m-%d')):
    return freq_decay, n_views, init_freq, s_until


@logger.catch()
def make_hash(password):  # returns 'method:salt:hash'
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)


@logger.catch()
def get_weight(initial_freq: int, num_views: int, decay_rate: int) -> float:
    """returns weight used to randomly select a card. A card's probablility of selection decreases logarithmically
    with num_views. The rate of decay is determined by decay_rate from 1-10. Higher decay_rate makes
    frequency of cards decline faster."""
    if num_views > gc.MAX_INFREQUENCY:
        num_views = gc.MAX_INFREQUENCY
    try:
        weight = initial_freq * math.e ** -(num_views / (gc.FREQUENCY_DECAY_RATE_MAX - decay_rate + 1))
    except ZeroDivisionError:
        logger.error('Decay rate must be 1-10. Check database.')
        weight = 0
    return weight


@logger.catch()
def add_missing(card: dict) -> dict:
    """
    Card records from database have this structure:
    {
    'id': 'rec203420932834098',
    'fields': {
        'card_id': ...,
        'tags': ...,
        ...}
    }


    When db values are None, '' or False, Airtable db returns a dict with that key absent. This func adds the
    missing keys and None values.

    card_datafield_names is a global list, so we only have to change that one constant when adding
    fields to db (including fields for  the named tuple we use for processing and passing card data. These are:
     'rec_id', 'card_id', 'num_views', 'initial_frequency', 'frequency_decay', 'weight', 'tags', 'skip_until', 'archived'
    """

    updated_card = {k: card['fields'][k] if k in card['fields'].keys() else None for k in card_datafield_names}
    updated_card['rec_id'] = card['id'] # returning a flattened dict where 'rec_id' is placed at same level as 'card_id'
    return updated_card

def single_newlines(bd):
    """Removes multiple newlines from body text that are inserted by CKEditor"""
    pass
# TODO: Add body of posts to cache
def write_cache(all_cards):
    with open(cache_file, 'w') as cache:
        card_json = [card._asdict() for card in all_cards]
        json.dump(card_json, cache, indent=4)

# TODO: Implement read_cache & test
def read_cache():
    with open(cache_file) as cache:
        cache_data = cache.readlines()
        card_json = [line.json() for line in cache_data]
        return card_json


# This function is required by Flask Login Manager.
@logger.catch()
@login_manager.user_loader
def load_user(id):
    try:
        user_data = user_table.first(formula=match({"user_id": id}))['fields']
        user = User(
            id=user_data['user_id'],
            user_name=user_data['user_name'],
            email=user_data['email'],
            password_hash=user_data['password_hash']
        )
    except ConnectionError:
        logger.error(f'Connection Error. Unable to load user from id.')
    return user


def is_admin():
    # User with id 1 in database is the admin for the blog
    if current_user.is_authenticated and current_user.id == 1:
        return True
    return False


# Decorator functions
def admin_only(func):
    @wraps(func)
    # This line is required so that flask doesn't see the multiple routes assigned to the same function ('wrapper')
    #  See https://stackoverflow.com/questions/17256602/assertionerror-view-function-mapping-is-overwriting-
    #  an-existing-endpoint-functi
    def wrapper(*args, **kwargs):
        if not is_admin() or current_user.is_anonymous:
            flash('403 Not authorized. Please log in as admin')
            return redirect(url_for('login'), 403)
            # abort(403)
        return func(*args, **kwargs)

    return wrapper


def logged_in_only(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            logger.warning('This function requires log in. Redirected to login.')
            flash('You must be logged in')
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper


@logger.catch()
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        formula = match({"email": request.form.get('email').lower()})
        try:
            user_data_raw = user_table.first(formula=formula)
        except ConnectionError:
            logger.error("Connection error. Unable to connect to database.")
        if user_data_raw:
            user_data = user_data_raw['fields']
            logger.error(f'Trying to add email: {request.form.get("email")}. Found: {user_data["email"]}')
            flash('Email already in use. Log in instead')
            return redirect(url_for('login'))
        try:
            response_from_db = user_table.create(
                {'user_name': request.form.get('name'),
                 'email': request.form.get('email').lower(),
                 'password_hash': make_hash(request.form.get('password'))},
            )
            logger.info(f'Registered new user with database: {response_from_db}')
            user_data = response_from_db['fields']
            user = User(
                id=user_data['user_id'],
                user_name=user_data['user_name'],
                email=user_data['email'],
                password_hash=user_data['password_hash']
            )
            # user.id = user.user_id
            login_user(user)
            flash('Registered and logged in')
            return redirect(url_for('get_all_cards'))
        except ConnectionError:
            logger.error('Error connecting to database.')
            flash('Error connecting to database')
    return render_template("register.html", form=form)


@logger.catch()
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('show_card'))
    form = LoginForm()
    if request.method == 'POST':
        # user = User.query.filter_by(email=request.form.get('email').lower()).first()
        formula = match({"email": request.form.get('email')})
        try:
            user_data = user_table.first(formula=formula)['fields']
        except ConnectionError:
            logger.error('Connection error. Error connecting to database (e.g too many retries')
            flash('Error connecting to database')
            return redirect(url_for('login'))
        user = User(
            id=user_data['user_id'],
            user_name=user_data['user_name'],
            email=user_data['email'],
            password_hash=user_data['password_hash']
        )
        logger.info(f'User: {user.user_name}')
        if user:
            if check_password_hash(user.password_hash, request.form.get('password')):
                login_user(user)
                flash('Logged in successfully.')
                return redirect(url_for('show_card'))
            else:
                flash('Password incorrect.')
        else:
            flash('Email not registered')
    return render_template('login.html', form=form, logged_in=current_user.is_authenticated)


@logger.catch()
@app.route('/logout')
def logout():
    logout_user()
    flash("Logged out")
    return redirect(url_for('login'))


@logger.catch()
@app.route("/", methods=['GET', 'POST'])
# @logged_in_only
def show_card():
    card_id = request.args.get("card_id")
    if not card_id:
        card_id = sched.get_next_card().card_id
    try:
        requested_card_raw = card_table.first(formula=match({"card_id": card_id}))
        requested_card = add_missing(requested_card_raw)
        # logger_text = 'Retrieved card:\n{}'.format("\n".join([str(requested_card[field]) for field
        # in requested_card.keys() if field != "body"]))
        # logger.debug(logger_text)
    except ConnectionError:
        logger.error('Unable to connect to database.')
    skip_form = SkipCardForm(days_to_skip=1, card_id=card_id)
    if skip_form.validate_on_submit():
        logger.debug(f'received back from form - card: {skip_form.card_id.data}, type: {type(skip_form.card_id.data)}, '
                     f'days to skip: {skip_form.days_to_skip.data}, type: {type(skip_form.days_to_skip.data)}')
        sched.skip_card(int(skip_form.card_id.data), skip_form.days_to_skip.data)
        return redirect(url_for("show_card", card_id=card_id))
    logger.debug(f'Card data passed to template: Card {requested_card["card_id"]}: {requested_card["title"]}')
    return render_template("card_and_image.html",
                           card=requested_card,
                           is_admin=is_admin(),
                           logged_in=current_user.is_authenticated,
                           dark_mode=False,
                           form=skip_form,
                           )


@logger.catch()
@app.route('/index', methods=['GET', 'POST'])
# @logged_in_only
def get_all_cards():
    try:
        card_data_raw = card_table.all(
            fields=['card_id', 'title', 'body', 'author', 'skip_until', 'tags', 'date_created', 'archived'])
        if card_data_raw:

            card_data_unsorted = [add_missing(card) for card in card_data_raw]
            card_data = sorted(card_data_unsorted, key=lambda card: card['card_id'])
            all_tags_nested = [card['tags'].split(' ') for card in card_data if card['tags']]  # a list of lists
            all_tags = set([item for sublist in all_tags_nested for item in sublist]) # Produces set from flattened list
            # ^ Is essentially a nested loop, i.e. for sublist in all_tags_nested: for item in sublist: yield item
            logger.debug(f'All tags {all_tags}')
            logger.debug(f'A few records: {card_data[:3]}')
            return render_template("index.html",
                                   all_cards=card_data,
                                   all_tags=all_tags,
                                   logged_in=current_user.is_authenticated,
                                   is_admin=is_admin()
                                   )
        flash('Unable to retrieve records from database')
        logger.error('Unable to retrieve records from database')
    except ConnectionError:
        flash('Unable to establish connection with db.')
        logger.error('Unable to establish connection with db.')
    return redirect(url_for('login'))


@logger.catch()
@app.route("/new-card", methods=['GET', 'POST'])
@logged_in_only
def add_new_card():
    form = CreateCardForm(num_views=0,
                          initial_frequency=gc.INITIAL_FREQUENCY_DEFAULT,
                          frequency_decay=gc.FREQUENCY_DECAY_DEFAULT,
                          skip_until=dt.datetime.strptime(gc.SKIP_UNTIL_DATE_DEFAULT, '%Y-%m-%d'))
    if form.validate_on_submit():
        # clean responses, insert defaults for None
        title, body, img_url = sanitize(form.title.data, form.body.data, form.img_url.data)
        body = body.replace("\n\n\n", "\n\n")
        logger.debug(f'Form returned: frequency_decay {form.frequency_decay.data}, num_views {form.num_views.data}, '
                     f'initial_frequency {form.initial_frequency.data}, skip_until {form.skip_until.data}, type {type(form.skip_until.data)}.')
        frequency_decay, num_views, initial_frequency, skip_until_response = default_if_none(form.frequency_decay.data,
                                                form.num_views.data, form.initial_frequency.data, form.skip_until.data)
        skip_until = skip_until_response.strftime('%Y-%m-%d')
        tags = clean(form.tags.data, strip=True)
        logger.debug(
            f'Attempting to create card with title: {title}, img_url: {img_url}, author {current_user.user_name}, '
            f'freq_decay: {frequency_decay}, tags: {tags}, '
            f'num_views: {num_views}, init_freq: {initial_frequency}, skip_until: {skip_until}, body: {body}')
        try:
            response = card_table.create({
                'title': title,
                'img_url': img_url,
                'author': current_user.user_name,
                'body': body,
                'num_views': num_views,
                'initial_frequency': initial_frequency,
                'frequency_decay': frequency_decay,
                'tags': tags,
                'skip_until': skip_until,
            })
            logger.info(f'New card created. Response: {response}')
            new_card = add_missing(response)
            flash('New card created successfully')
            return redirect(url_for("show_card", card_id=new_card['card_id']))
        except ConnectionError:
            logger.error(f'Connection Error. Unable to connect to database. Response {response}')
            flash(f'Connection Error. Unable to connect to database. Card not added.')
    return render_template("new-card.html", form=form)


@logger.catch()
@app.route("/edit-card/<int:card_id>", methods=['GET', 'POST'])
@admin_only
def edit_card(card_id):
    formula = match({'card_id': card_id})
    try:
        card_data_raw = card_table.first(formula=formula)
    except ConnectionError:
        logger.error('Unable to connect to database')
    if card_data_raw:
        card = add_missing(card_data_raw)
        logger.debug(f'Retrieved card to edit from database: {card}')
        card['body'] = card['body'].replace('\n', '<br />')  # CKEditor makes \n newlines duplicate when saving edits
    else:
        flash('404: Link does not exist/no such card')
        logger.error('404: Link does not exist/no such card')
        return redirect(url_for('show_card'), 404)
    logger.debug(f'Raw body text from db: {card["body"]}')
    edit_form = CreateCardForm(
        title=card['title'],
        img_url=card['img_url'],
        author=card['author'],
        body=card['body'],
        num_views=card['num_views'],
        initial_frequency=card['initial_frequency'],
        frequency_decay=card['frequency_decay'],
        skip_until=dt.datetime.strptime(gc.SKIP_UNTIL_DATE_DEFAULT, '%Y-%m-%d'),
        tags=card['tags']
    )
    if edit_form.validate_on_submit():
        title, body, img_url = sanitize(edit_form.title.data, edit_form.body.data, edit_form.img_url.data)
        # logger.debug(
        #     f'Form returned: frequency_decay {edit_form.frequency_decay.data}, num_views {edit_form.num_views.data}, '
        #     f'initial_frequency {edit_form.initial_frequency.data}, skip_until_response {edit_form.skip_until.data}, '
        #     f'type {type(edit_form.skip_until.data)}.')

        # body = body.replace('<br /><br /><br />', '<br />')
        # body = body.replace('<br /><br />', '<br />')
        # body = body.replace('<br />', '\n')
        # body = body.replace('<br><br><br>', '<br>')
        # body = body.replace('<br><br>', '<br>')
        # body = body.replace('<br>', '\n')
        # body = body.replace('\n\n\n', '\n')
        # body = body.replace('\n\n', '\n')

        frequency_decay, num_views, initial_frequency, skip_until_response = default_if_none(
            edit_form.frequency_decay.data,
            edit_form.num_views.data,
            edit_form.initial_frequency.data,
            edit_form.skip_until.data)
        tags = clean(edit_form.tags.data, strip=True)
        skip_until = skip_until_response.strftime('%Y-%m-%d')
        logger.debug(
            f'Attempting to edit card with title: {title}, img_url: {img_url}, author {current_user.user_name}, '
            f'freq_decay: {frequency_decay}, tags: {tags}, '
            f'num_views: {num_views}, init_freq: {initial_frequency}, skip_until: {skip_until}, body: {body}')
        try:
            response = card_table.update(
                card['rec_id'],
                {
                    'title': title,
                    'img_url': img_url,
                    'body': body,
                    'num_views': num_views,
                    'initial_frequency': initial_frequency,
                    'frequency_decay': frequency_decay,
                    'tags': tags,
                    'skip_until': skip_until
                })
            logger.info(f'Card updated successfully. Response: {response}')
        except ConnectionError:
            logger.error(f'Connection Error. Unable to connect to database. Response {response}')
            flash(f'Connection Error. Unable to connect to database. Card not updated.')
        return redirect(url_for("show_card", card_id=card_id))
    return render_template("new-card.html", logged_in=current_user.is_authenticated, is_edit=True, form=edit_form,
                           card=card)


@logger.catch()
@app.route("/archive-card/<int:card_id>")
@admin_only
def archive_card(card_id):
    rec_id = card_table.first(formula=match({"card_id": card_id}))['id']
    logger.debug(f'Found card to archive. Rec ID is: {rec_id}')
    try:
        card_table.update(rec_id, {'archived': True})
        logger.info(f'Card {card_id} archived successfully')
    except ConnectionError:
        flash('Unable to connect to database')
        logger.error('Unable to connect to database')
    return redirect(url_for('show_card'))


@app.route("/about")
def about():
    return render_template("about.html")


@logged_in_only
@app.route("/contact")
def contact():
    return render_template("contact.html")


sched = Schedule()

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5001)
