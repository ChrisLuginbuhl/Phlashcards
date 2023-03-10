from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, IntegerField, PasswordField, HiddenField, DateField
from wtforms.validators import DataRequired, URL, NumberRange
from flask_ckeditor import CKEditorField
import global_constants as gc


# from main import FREQUENCY_DECAY_RATE_MAX, FREQUENCY_DECAY_DEFAULT, INITIAL_FREQUENCY_MAX, INITIAL_FREQUENCY_DEFAULT
##WTForm
class CreateCardForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired()])
    img_url = StringField("Image URL (optional)")
    num_views = IntegerField("Number of Views")
    initial_frequency = IntegerField(f"Initial Frequency (1 = v. low, {gc.INITIAL_FREQUENCY_MAX} = very high, "
                                     f"default={gc.INITIAL_FREQUENCY_DEFAULT})",
                                     validators=[DataRequired(), NumberRange(min=1, max=10,
                                     message=f'Initial Frequency must be an integer between 1 '
                                             f'and {gc.INITIAL_FREQUENCY_MAX}')])
    frequency_decay = IntegerField(f"Frequency Decay (1=v. slow, {gc.FREQUENCY_DECAY_RATE_MAX} = v. fast, "
                                   f"default={gc.FREQUENCY_DECAY_DEFAULT})",
                                   validators=[DataRequired(),
                                   NumberRange(min=1, max=gc.FREQUENCY_DECAY_RATE_MAX,
                                               message=f'Frequency Decay must be an integer '
                                                       f'between 1 and {gc.FREQUENCY_DECAY_RATE_MAX}')])
    tags = StringField("Tags (use space to separate)")
    body = CKEditorField("Card Body")
    skip_until = DateField(f"Skip Until YYYY-mm-dd (default: don't skip): ")
    submit = SubmitField("Submit Card")


class SkipCardForm(FlaskForm):
    days_to_skip = IntegerField("Days to skip", validators=[DataRequired(),
                                                        NumberRange(min=1,
                                                                    message=f'"Number of days to skip this card" must'
                                                                            f' be an integer greater than zero')])
    card_id = HiddenField()
    submit = SubmitField("Submit")


class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    name = StringField("Username", validators=[DataRequired()])
    submit = SubmitField('Sign me up!')


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField('Log me in')
