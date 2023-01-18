'''
Pimsleur Flashcards
Chris Luginbuhl

This flashcard web app is intended for learning & remembering anything - language, facts, stories, people's names...

It uses training frequency inspired by the Pimsleur language courses to ask you things just before you're about to
forget them, e.g. after 5 minutes, after 20 minutes, after an hour, after 1 day, 3, days, etc.
The newest flash cards are shown with the greatest frequency.

It is intended to be deployed using Airtable (for db) and Python Anywhere (now that Heroku/Postgres is not free!)
The app also supports multiple users in the same database.

Makes use of some code from Udemy/App Brewery's 100 Days of Code day 64 and 69 for user registration, login, etc.

Uses Flask for rendering html, jinja for variables, flask-wtf for forms, pyairtable for database.
'''

import os
import global_constants as gc
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_bootstrap import Bootstrap
from flask_ckeditor import CKEditor
from datetime import date
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, login_user, LoginManager, login_required, current_user, logout_user
from forms import CreateCardForm, RegisterForm, LoginForm
from secrets import token_hex
from functools import wraps
import math
import random
from collections import namedtuple
import bleach
from pyairtable import Api, Base, Table
from pyairtable.formulas import match
from flask_debugtoolbar import DebugToolbarExtension
import requests
import logging

# Run Pydoc window with: python -m pydoc -p <port_number>

# TODO 1: Check all routes on debug toolbar "routes" e.g. /ckeditor/static/<path:filename> for login_required
# TODO 2: Allow uploading images to Firebase or similar for permanent URL
# TODO 3: implement tags
# TODO 4: implement tag filters
# TODO  : card layout for tags
# TODO 5: Add 'skip for today'
# TODO 6: ---COMPLETED----Different decay rates?
# TODO 7: check if max infrequency works, i.e. what happens after 20 views
# TODO 8: Card layout - buttons at top? swipe left?
# TODO 9: Implement Delete Card (or Archive Card)
# TODO 10: Decide what to do with /index. Starred cards? Tags? Oldest/newest/random?
# TODO 11: ---COMPLETED---Implement frequency decay rate
# TODO 12: Connect DB tables (author name and ID)
# TODO 13: Launch 1.0 on PAnywhere
# TODO 14: Preload body and img for all cards in queue rather than retrieving one at at time




Card_data = namedtuple('Card_data', ['rec_id', 'id', 'num_views', 'initial_frequency', 'frequency_decay', 'weight'])

Flask.secret_key = token_hex(16)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('APP_SECRET_KEY')
ckeditor = CKEditor(app)
Bootstrap(app)
app.debug = True  # This is for debug toolbar
toolbar = DebugToolbarExtension(app)
logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)

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
    def __init__(self, user_name, email, password_hash, id=0,):
        self.id = id
        self.user_name = user_name
        self.email = email
        self.password_hash = password_hash


class Schedule:
    '''Creates a queue of cards and serves the next card'''
    # Creates a queue of card ids according to these rules:
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
    # 1. Get all record_id, card id, initial_frequency, num_views, skip_for_today from
    #      database (don't need to load title, images, body, etc)
    # 2. Calculate weights (initial_frequency * exponential decay according to num views)
    #
    # Refresh queue:
    # 3. Create a list of eligible cards (cards not in the queue already, not skip for today, etc)
    # 4. Pick a card from eligible cards list randomly, add it to the end of the queue, remove it from eligible cards list
    # 5. repeat step 4 until queue is full
    # 6. Method get_next_card(): Keep an index, and serve this card ID from the queue when asked.
    # 7. When index reaches end of queue, update num_views (and "do not show today") in db for all cards in queue
    #   (Option to implement: Also do 7a) if/when no new card for 2 minutes)
    # 8. Update eligible cards from db (removing everything in queue)
    # 9. Clear the queue
    # 10.GOTO step 4
    #
    # Summary:
    # fill queue with eligible cards, removing them one at a time from eligible cards list
    # serve cards til end of queue
    # update num_views (and "do not show today") in db
    # update eligible cards from db (removing everything in queue)
    # fill queue from eligible cards



    def __init__(self):
        self.index = 0
        self.queue = []
        self.eligible_cards = []

    def fill_queue(self):
        # Get eligible cards from queue
        # Retrieve data from all cards in database and return it in a list of
        # named tuples including calculated weights
        card_data = card_table.all(fields = ['card_id', 'num_views', 'initial_frequency', 'frequency_decay'])
        rec_ids = [card['id'] for card in card_data]
        ids = [card['fields']['card_id'] for card in card_data]
        num_views = [card['fields']['num_views'] for card in card_data]
        frequency_decay = [card['fields']['frequency_decay'] for card in card_data]
        initial_frequencies = [card['fields']['initial_frequency'] for card in card_data]
        # weights = [init_freq * EXP_WEIGHTS[num_views[idx]] for idx, init_freq in enumerate(initial_frequencies)]
        weights = [get_weight(init_freq, num_views[idx], frequency_decay[idx]) for idx, init_freq in
                   enumerate(initial_frequencies)]
        all_cards = [Card_data(rec_ids[idx], id, num_views[idx], initial_frequencies[idx],
                               frequency_decay[idx], weights[idx]) for idx, id in enumerate(ids)]
        # ^ List comp of named tuples "Card_data"
        self.eligible_cards = list(set(all_cards) - set(self.queue))  # much faster than list comp

        # Now fill the queue
        self.queue = []
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
                abort
        print(f'queue is: {[card.id for card in self.queue]}')

    def get_next_card(self) -> Card_data:
        if not self.queue:
            self.fill_queue()  # This runs once, when the app opens.
        next_card = self.queue[self.index]
        if self.index == gc.QUEUE_SIZE - 1:
            self.update_db()
            self.fill_queue()
            self.index = 0
        else:
            self.index += 1
            print(f'Next card: {next_card.id}. '
                  f'num_views: {next_card.num_views}',
                  f'Init_freq: {next_card.initial_frequency}, '
                  f'decay rate: {next_card.frequency_decay}, '
                  f'weight: {next_card.weight}')


        return next_card

    def update_db(self):
        updates_list = [{'id': card.rec_id, "fields": {"num_views": card.num_views + 1}} for card in self.queue]
        logger.debug(f'Updates list: {updates_list}')
        card_table.batch_update(updates_list)


# HELPER FUNCTIONS
def check_is_url_image(image_url):
    image_formats = ("image/png", "image/jpeg", "image/jpg")
    r = requests.head(image_url)
    if r.headers["content-type"] in image_formats:
        return image_url
    return gc.BROKEN_LINK_IMG_URL

def sanitize(raw_title, raw_body, raw_img_url):
    body = bleach.clean(raw_body, tags=['em', 'p', 'i', 'br'])
    title = bleach.clean(raw_title)
    img_url = check_is_url_image(raw_img_url)
    return title, body, img_url

def make_hash(password):  # returns 'method:salt:hash'
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

def get_weight(initial_freq: int, num_views: int, decay_rate: int) -> float:
    """returns weight used to randomly select a card. A card's probablility of selection decreases logarithmically
    with num_views. The rate of decay is determined by decay_rate. decay_rate is 1-10. Higher decay_rate makes
    frequency of cards decline faster."""
    if num_views > gc.MAX_INFREQUENCY:
        num_views = gc.MAX_INFREQUENCY
    try:
        weight = initial_freq * math.e ** -(num_views / (gc.FREQUENCY_DECAY_RATE_MAX - decay_rate + 1))
    except ZeroDivisionError:
        print('Decay rate must be 1-10. Check database.')
    return weight


# This function is required by Flask Login Manager.
@login_manager.user_loader
def load_user(id):
    user_data = user_table.first(formula=match({"user_id": id}))['fields']
    user = User(
        id=user_data['user_id'],
        user_name=user_data['user_name'],
        email=user_data['email'],
        password_hash=user_data['password_hash']
    )
    return user


def is_admin():
    # User with id 1 in database is the admin for the blog
    if current_user.is_authenticated and current_user.id == 1:
        return True
    else:
        return False


# Decorator functions
def admin_only(func):
    @wraps(func)
    # This line is required so that flask doesn't see the multiple routes assigned to the same function ('wrapper')
    #  See https://stackoverflow.com/questions/17256602/assertionerror-view-function-mapping-is-overwriting-
    #  an-existing-endpoint-functi
    def wrapper(*args, **kwargs):
        if not is_admin() or current_user.is_anonymous:
            # flash('403 Not authorized. Please log in as admin')
            # return redirect(url_for('login'), 403)
            abort(403)
        return func(*args, **kwargs)
    return wrapper


def logged_in_only(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper



@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        formula = match({"email": request.form.get('email').lower()})
        user_data_raw = user_table.first(formula=formula)
        if user_data_raw:
            user_data = user_data_raw['fields']
            print(f'Trying to add email: {request.form.get("email")}. Found: {user_data["email"]}')
            flash('Email already in use. Log in instead')
            return redirect(url_for('login'))
        response_from_db = user_table.create(
            {'user_name':request.form.get('name'),
            'email':request.form.get('email').lower(),
            'password_hash':make_hash(request.form.get('password'))},
        )
        print(f'Registered new user with database: {response_from_db}')
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
    return render_template("register.html", form=form)


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
        except requests.exceptions.ConnectionError:
            logger.error('Connection error. Error connecting to database (e.g too many retries')
            flash('Error connecting to database')
            return redirect(url_for('login'))
        user = User(
            id=user_data['user_id'],
            user_name=user_data['user_name'],
            email=user_data['email'],
            password_hash=user_data['password_hash']
        )
        print(f'User: {user}')
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


@app.route('/logout')
def logout():
    logout_user()
    flash("Logged out")
    return redirect(url_for('login'))



@app.route("/")
# @logged_in_only
def show_card():
    card_id = request.args.get("card_id")
    if not card_id:
        card_id =sched.get_next_card().id
    requested_card = card_table.first(formula=match({"card_id": card_id}))['fields']
    # logger.debug(f'Requested card body: {requested_card["body"]}')
    return render_template("card_and_image.html",
                           card=requested_card,
                           # comments=comments,
                           # form=comment_form,
                           is_admin=is_admin(),
                           logged_in=current_user.is_authenticated,
                           dark_mode=False,
                           )


@app.route('/index')
@logged_in_only
def get_all_cards():
    card_data_raw = card_table.all(fields=['card_id', 'title', 'body', 'author', 'date_created'])
    card_data_unsorted = [card["rec_id"].append(card["fields"]) for card in card_data_raw]
    card_data = sorted(card_data_unsorted, key=lambda card: card['card_id'])
    print(f'card data: {card_data}')
    return render_template("index.html",
                           all_cards=card_data,
                           logged_in=current_user.is_authenticated,
                           is_admin=is_admin()
                           )


@app.route("/card/<int:card_id>", methods=['GET', 'POST'])
@logged_in_only
def add_comment(card_id):
    card_id = request.args.get("id")
    ##  TODO: Get card from database
    return render_template("card_and_image.html",
                           card=card_id,
                           is_admin=is_admin(),
                           logged_in=current_user.is_authenticated,
                           dark_mode=True,
                           )


@app.route("/new-card", methods=['GET', 'POST'])
@logged_in_only
def add_new_card():
    form = CreateCardForm(num_views=0,
                          initial_frequency=gc.INITIAL_FREQUENCY_DEFAULT,
                          frequency_decay=gc.FREQUENCY_DECAY_DEFAULT)
    if form.validate_on_submit():
        # clean_html_body = BeautifulSoup(form.body.data).get_text()
        title, body, img_url = sanitize(form.title.data, form.body.data, form.img_url.data)
        response = card_table.create({
            'title': title,
            'img_url': img_url,
            'author': current_user.user_name,
            'body': body,
            'num_views': form.num_views.data,
            'initial_frequency': form.initial_frequency.data,
            'frequency_decay': form.frequency_decay.data,
        })
        print(f'New card created. Response: {response}')
        return redirect(url_for("get_all_cards"))
    return render_template("new-card.html", form=form)


@app.route("/edit-card/<int:card_id>", methods=['GET', 'POST'])
@admin_only
def edit_card(card_id):
    formula = match({'card_id': card_id})
    card_data_raw = card_table.first(formula=formula)
    rec_id = card_data_raw['id']
    if card_data_raw:
        card = card_data_raw['fields']
    else:
        flash('404: Link does not exist/no such card')
        return redirect(url_for('show_card'), 404)
    edit_form = CreateCardForm(
        title=card['title'],
        img_url=card['img_url'],
        author=card['author'],
        body=card['body'],
        num_views=card['num_views'],
        initial_frequency=card['initial_frequency'],
        frequency_decay=card['frequency_decay'],
    )
    if edit_form.validate_on_submit():
        title, body, img_url = sanitize(edit_form.title.data, edit_form.body.data, edit_form.img_url.data)
        card_table.update(
            rec_id,
            {
                'title': title,
                'img_url': img_url,
                'body': body,
                'num_views': edit_form.num_views.data,
                'initial_frequency': edit_form.initial_frequency.data,
            })
        return redirect(url_for("show_card", card_id=card_id))
    return render_template("new-card.html", logged_in=current_user.is_authenticated, is_edit=True, form=edit_form)


@app.route("/archive-card/<int:card_id>")
@admin_only
def archive_card(card_id):
    rec_id = card_table.first(formula=match({"card_id": card_id})['fields'])
    logger.log(f'Record to archive rec_id: {rec_id}')
    card_table.update(rec_id, {'archive': 1})

    return redirect(url_for('get_all_cards'))


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
