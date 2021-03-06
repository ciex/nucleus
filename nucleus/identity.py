# -*- coding: utf-8 -*-
"""
    nucleus.identity
    ~~~~~

    Identity and account models

    :copyright: (c) 2015 by Vincent Ahrend.
"""
import datetime

import content
import context

from flask import url_for
from flask.ext.login import current_user, UserMixin
from hashlib import sha256
from uuid import uuid4
from sqlalchemy import or_, Column, Integer, String, Boolean, DateTime, Table, \
    ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session

from . import logger, ATTENTION_CACHE_DURATION, ATTENTION_MULT, \
    ExecutionTimer, CONVERSATION_LIST_CACHE_DURATION, TOP_THOUGHT_CACHE_DURATION, \
    UnauthorizedError, PERSONA_MOVEMENTS_CACHE_DURATION, REPOST_MINDSET_CACHE_DURATION, \
    SUGGESTED_MOVEMENTS_CACHE_DURATION, MEMBER_COUNT_CACHE_DURATION, \
    MINDSPACE_TOP_THOUGHT_CACHE_DURATION, TOP_MOVEMENT_CACHE_DURATION, \
    movement_chat

from .base import Model, BaseModel
from .connections import cache
# from .content import Notification, Thought, Blog, Upvote
# from .context import Dialogue, Mindset, Mindspace


class User(Model, UserMixin):
    """A user of the website"""

    __tablename__ = 'user'

    id = Column(String(32), primary_key=True)

    active = Column(Boolean(), default=True)
    authenticated = Column(Boolean(), default=True)
    created = Column(DateTime)
    email = Column(String(128))
    modified = Column(DateTime)
    pw_hash = Column(String(64))
    validated_on = Column(DateTime)
    signup_code = Column(String(128))

    # Email preferences
    email_react_private = Column(Boolean(), default=True)
    email_react_reply = Column(Boolean(), default=True)
    email_react_mention = Column(Boolean(), default=True)
    email_react_follow = Column(Boolean(), default=False)
    email_system_security = Column(Boolean(), default=True)
    email_system_features = Column(Boolean(), default=False)
    email_catchall = Column(Boolean(), default=False)

    # Relations
    active_persona = relationship("Persona",
        primaryjoin="persona.c.id==user.c.active_persona_id", post_update=True,
        lazy="joined")
    active_persona_id = Column(String(32),
        ForeignKey('persona.id', name="fk_active_persona"))

    def __repr__(self):
        return "<User {}>".format(self.email.encode('utf-8'))

    def check_password(self, password):
        """Return True if password matches user password

        Args:
            password (String): Password entered by user in login form
        """
        pw_hash = sha256(password).hexdigest()
        return self.pw_hash == pw_hash

    def email_allowed(self, notification):
        """Return True if this user allows the notification to be sent by email

        Args:
            notification (Notification): Notification object

        Returns:
            Boolean: True if notification should be sent as email
        """
        rv = False
        if not self.email_catchall:
            if notification.email_pref:
                if getattr(self, notification.email_pref) is True:
                    c = content.Notification.query \
                        .filter_by(recipient=notification.recipient) \
                        .filter_by(url=notification.url) \
                        .filter_by(unread=True) \
                        .filter(content.Notification.id != notification.id)

                    if c.count() == 0:
                        rv = True
                    else:
                        logger.debug(
                            "{} not sent by email because {} unread notifications point to same url '{}'".format(
                                notification, c.count(), notification.url))
                else:
                    logger.debug(
                        "{} not sent by email because of '{}'".format(
                            notification, notification.email_pref))
            else:
                logger.warning(
                    "{} is missing email_pref attribute".format(notification))
        else:
            logger.debug(
                "{} not sent because of email catchall pref".format(
                    notification))
        return rv

    def get_id(self):
        return self.id

    def is_active(self):
        return self.active

    def is_anonymous(self):
        return False

    def is_authenticated(self):
        return self.authenticated

    def set_password(self, password):
        """Set password to a new value

        Args:
            password (String): Plaintext value of the new password
        """
        pw_hash = sha256(password).hexdigest()
        self.pw_hash = pw_hash

    def validate(self):
        """Set the validated_on property to the current time"""
        self.validated_on = datetime.datetime.utcnow()

    @property
    def validated(self):
        """Is True if validated_on has been set"""
        return self.validated_on is not None

    def valid_signup_code(self, signup_code):
        """Return True if the given signup code is valid, and less than 7 days
        have passed since signup.

        Args:
            signup_code (String): 128byte string passed in registration email
        """
        if signup_code != self.signup_code:
            return False

        if (datetime.datetime.utcnow() - self.created) > datetime.timedelta(days=7):
            return False

        return True


class Identity(Model):
    """Abstract identity, superclass of Persona and Movement

    Attributes:
        _insert_required: Attributes that are serialized
        id: 32 byte ID generated by uuid4().hex
        username: Public username of the Identity, max 80 bytes
        crypt_private: Private encryption RSA key, JSON encoded KeyCzar export
        crypt_public: Public encryption RSA key, JSON encoded KeyCzar export
        sign_private: Private signing RSA key, JSON encoded KeyCzar export
        sign_public: Public signing RSA key, JSON encoded KeyCzar export
        modified: Last time this Identity object was modified, defaults to now
        blog: Mindset containing this Identity's blog

    """

    __tablename__ = "identity"

    __mapper_args__ = {
        'polymorphic_identity': 'identity',
        'polymorphic_on': "kind"
    }

    id = Column(String(32), primary_key=True)

    color = Column(String(6), default="B8C5D6")
    created = Column(DateTime())
    kind = Column(String(32))
    modified = Column(DateTime(), default=datetime.datetime.utcnow())
    username = Column(String(80))

    # Relations
    blog_id = Column(String(32), ForeignKey('mindset.id'))
    blog = relationship('Mindset', primaryjoin='mindset.c.id==identity.c.blog_id')

    mindspace_id = Column(String(32), ForeignKey('mindset.id'))
    mindspace = relationship('Mindset', primaryjoin='mindset.c.id==identity.c.mindspace_id')

    blogs_followed = relationship('Identity',
        secondary='blogs_followed',
        primaryjoin='blogs_followed.c.follower_id==identity.c.id',
        secondaryjoin='blogs_followed.c.followee_id==identity.c.id')

    def __repr__(self):
        try:
            name = self.username.encode('utf-8')
        except AttributeError:
            name = ""
        return "<ID @{} [{}]>".format(name, self.id[:6])

    def authorize(self, action, author_id=None):
        """Return True if this Identity authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.ACCESS_MODES)
            author_id (String): Identity ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if BaseModel.authorize(self, action, author_id=author_id):
            return (self.id == author_id)
        return False

    def notification_list(self, limit=5):
        return self.notifications \
            .filter_by(unread=True) \
            .order_by(content.Notification.modified.desc()) \
            .limit(limit) \
            .all()
#
# Setup follower relationship on Persona objects
#

t_blogs_followed = Table('blogs_followed',
    Model.metadata,
    Column('follower_id', String(32), ForeignKey('identity.id')),
    Column('followee_id', String(32), ForeignKey('identity.id'))
)


class Persona(Identity):
    """A Persona represents a user profile

    Attributes:
        email: An email address, max 120 bytes

    """

    __tablename__ = "persona"
    __mapper_args__ = {
        'polymorphic_identity': 'persona'
    }

    id = Column(String(32), ForeignKey('identity.id'), primary_key=True)

    auth = Column(String(32))
    last_connected = Column(DateTime(), default=datetime.datetime.now())
    email = Column(String(120))
    session_id = Column(String(32))

    user_id = Column(String(32),
        ForeignKey('user.id', use_alter=True, name="fk_persona_user"))
    user = relationship('User',
        backref="associations", primaryjoin="user.c.id==persona.c.user_id")

    def __repr__(self):
        try:
            name = self.username.encode('utf-8')
        except AttributeError:
            name = "encoding_error"
        return "<Persona @{} [{}]>".format(name, self.id[:6])

    def authorize(self, action, author_id=None):
        """Return True if this Persona authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.ACCESS_MODES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        if Identity.authorize(self, action, author_id=author_id):
            return (self.id == author_id)
        return False

    @cache.memoize(timeout=ATTENTION_CACHE_DURATION)
    def get_attention(self):
        """Return a numberic value indicating attention this Persona has received

        Returns:
            integer: Attention as a positive integer
        """
        timer = ExecutionTimer()
        ses = Session.object_session(self)
        thoughts = ses.query(content.Thought) \
            .filter_by(author=self)

        rv = int(sum([t.hot() for t in thoughts]) * ATTENTION_MULT)
        timer.stop("Generated attention value for {}".format(self))
        return rv

    attention = property(get_attention)

    @cache.memoize(timeout=CONVERSATION_LIST_CACHE_DURATION)
    def conversation_list(self):
        """Return a list of conversations this persona had

        Returns:
            list: List of dicts with keys
                persona_id: id of the other side of the conversation
                persona_username: respective username
                modified: last thought in the conversation
        """
        timer = ExecutionTimer()
        convs_query = context.Dialogue.query \
            .filter(or_(
                context.Dialogue.author == self,
                context.Dialogue.other == self
            )).all()

        convs = list()
        for c in convs_query:
            last_post = c.index.order_by(content.Thought.created.desc()).first()
            if last_post:
                other = c.other if c.author == self else c.author
                conv_dict = dict(
                    persona_id=other.id,
                    persona_username=other.username,
                    modified=last_post.created)
                convs.append(conv_dict)
        convs = sorted(convs, reverse=True, key=lambda c: c["modified"]
            if c["modified"] else datetime.datetime.utcfromtimestamp(0))
        timer.stop("Generated conversation list for {}".format(self))
        return convs

    @cache.memoize(timeout=TOP_THOUGHT_CACHE_DURATION)
    def frontpage_sources(self):
        """Return mindset IDs that provide posts for this Persona's frontpage

        Returns:
            list: List of IDs
        """
        source_idents = set()
        for source in self.blogs_followed:
            if isinstance(source, Movement) and source.active_member(persona=self):
                source_idents.add(source.mindspace_id)
            source_idents.add(source.blog_id)

        return source_idents

    def get_absolute_url(self):
        return url_for('web.persona', id=self.id)

    def get_email_hash(self):
        """Return sha256 hash of this user's email address"""
        return sha256(self.email).hexdigest()

    @cache.memoize(timeout=PERSONA_MOVEMENTS_CACHE_DURATION)
    def movements(self):
        """Return movements in which this Persona is an active member

        Returns:
            list: List of dicts with keys 'id', 'username' for each movement
        """
        timer = ExecutionTimer()
        user_movements = Movement.query \
            .join(MovementMemberAssociation) \
            .filter(MovementMemberAssociation.active == True) \
            .filter(MovementMemberAssociation.persona
                 == current_user.active_persona) \
            .order_by(Movement.username)

        rv = [dict(id=m.id, username=m.username)
            for m in user_movements]
        timer.stop("Generated movement list for {}".format(self))
        return rv

    @cache.memoize(timeout=REPOST_MINDSET_CACHE_DURATION)
    def repost_mindsets(self):
        """Return list of mindset IDs in which this persona might post

        Returns:
            list: mindset IDs
        """

        rv = []
        rv.append(self.mindspace)
        rv.append(self.blog)

        # Is a movement member
        rv = rv + context.Mindset.query \
            .join(Movement, Movement.mindspace_id == context.Mindset.id) \
            .filter(Movement.id.in_([m["id"] for m in self.movements()])).all()
        return [ms.id for ms in rv]

    @cache.memoize(timeout=SUGGESTED_MOVEMENTS_CACHE_DURATION)
    def suggested_movements(self):
        """Return a list of IDs for movements that are not followed but have
        many members.

        Returns:
            list: IDs of Movements
        """
        timer = ExecutionTimer()
        mov_selection = Movement.top_movements()
        user_movs = [mma.movement.id for mma in self.movement_assocs]
        rv = [m['id'] for m in mov_selection if m['id'] not in user_movs]
        timer.stop("Generated suggested movements for {}".format(self))
        return rv

    def toggle_following(self, ident):
        """Toggle whether this Persona is following a blog.

        Args:
            ident (Identity): Whose blog to follow/unfollow

        Returns:
            boolean -- True if the blog is now being followed, False if not
        """
        following = False

        try:
            self.blogs_followed.remove(ident)
            logger.info("{} is not following {} anymore".format(self, ident))
        except ValueError:
            self.blogs_followed.append(ident)
            following = True
            logger.info("{} is now following {}".format(self, ident))

        cache.delete_memoized(self.frontpage_sources)
        return following

    def toggle_movement_membership(self, movement, role="member",
            invitation_code=None):
        """Toggle whether this Persona is member of a movement.

        Also enables movement following for this Persona/Movement.

        Args:
            movement (Movement): Movement entity to be become member of
            role (String): What role to take in the movement. May be "member"
                or "admin"
            invitation_code (String): (Optional) If the movement is private
                an invitation code may be needed to join

        Returns:
            Updated MovementMemberAssociation object
        """
        if invitation_code and len(invitation_code) > 0:
            mma = MovementMemberAssociation.query \
                .filter_by(invitation_code=invitation_code) \
                .first()
        else:
            mma = MovementMemberAssociation.query \
                .filter_by(movement=movement) \
                .filter_by(persona=self) \
                .first()

        # Follow movement when joining
        if movement not in self.blogs_followed and (mma is None or not mma.active):
            logger.info("Setting {} to follow {}.".format(self, movement))
            self.toggle_following(movement)

        # Validate invitation code
        if mma is None or (mma.active is False and mma.invitation_code != invitation_code):
            if movement.private and current_user.active_persona != movement.admin:
                logger.warning("Invalid invitation code '{}'".format(invitation_code))
                raise UnauthorizedError("Invalid invitation code '{}'".format(invitation_code))

        if mma is None:
            logger.info("Enabling membership of {} in {}".format(self, movement))
            mma = MovementMemberAssociation(
                persona=self,
                movement=movement,
                role=role,
            )

        elif mma.active is False:
            mma.active = True
            mma.role = role
            logger.info("Membership of {} in {} re-enabled".format(self, movement))

        else:
            if self.id == movement.admin_id:
                raise NotImplementedError("Admin can't leave the movement")
            logger.info("Disabling membership of {} in {}".format(self, movement))
            mma.active = False
            mma.role = "left"

        # Reset caches
        cache.delete_memoized(movement.member_count)
        cache.delete_memoized(self.movements)
        cache.delete_memoized(self.repost_mindsets)
        cache.delete_memoized(self.frontpage_sources)

        return mma


class MovementMemberAssociation(Model):
    """Associates Personas with Movements"""

    __tablename__ = 'movementmember_association'
    __table_args__ = (UniqueConstraint(
        'movement_id', 'persona_id', name='_mma_uc'),)

    id = Column(Integer(), primary_key=True)
    movement_id = Column(String(32), ForeignKey('movement.id'))
    persona_id = Column(String(32), ForeignKey('persona.id'))
    persona = relationship("Persona",
        backref="movement_assocs", lazy="joined")

    # Role may be either 'admin' or 'member'
    active = Column(Boolean, default=True)
    created = Column(DateTime(), default=datetime.datetime.utcnow())
    description = Column(Text)
    last_seen = Column(DateTime(), default=datetime.datetime.utcnow())
    role = Column(String(16), default="member")
    invitation_code = Column(String(32))

    def __repr__(self):
        return "<Membership <Movement {}> <Persona {}> ({})>".format(
            self.movement.id[:6], self.persona.id[:6], self.role)


t_members = Table('members',
    Model.metadata,
    Column('movement_id', String(32), ForeignKey('movement.id')),
    Column('persona_id', String(32), ForeignKey('persona.id'))
)


class Movement(Identity):
    """Represents an entity that is comprised of users collaborating on thoughts

    Attributes:
        id (String): 32 byte ID of this movement
        description (String): Text decription of what this movement is about
        admin (Persona): Person that is allowed to make structural changes to the movement_id

    """

    __tablename__ = "movement"
    __mapper_args__ = {'polymorphic_identity': 'movement'}

    id = Column(String(32), ForeignKey('identity.id'), primary_key=True)

    description = Column(Text)
    state = Column(Integer(), default=0)
    private = Column(Boolean(), default=False)

    # Relations
    admin_id = Column(String(32), ForeignKey('persona.id'))
    admin = relationship("Persona", primaryjoin="persona.c.id==movement.c.admin_id")

    members = relationship("MovementMemberAssociation",
        backref="movement",
        lazy="dynamic")

    def __init__(self, *args, **kwargs):
        """Attach index mindset to new movements"""
        Identity.__init__(self, *args, **kwargs)
        self.blog = context.Blog(
            id=uuid4().hex,
            author=self,
            modified=self.created)

        self.mindspace = context.Mindspace(
            id=uuid4().hex,
            author=self,
            modified=self.created)

    def __repr__(self):
        try:
            name = self.username.encode('utf-8')
        except AttributeError:
            name = "(name encode error)"

        return "<Movement @{} [{}]>".format(name, self.id[:6])

    def active_member(self, persona=None):
        """Return True if persona or currently active Persona is an active
            member or admin

        Args:
            persona (Persona): Optional Persona. Will default to active Persona
                if left blank

        Returns:
            boolean: True if active member
        """
        rv = False

        if persona is None and current_user.is_anonymous() is False:
            persona = current_user.active_persona

        if persona:
            gms = MovementMemberAssociation.query \
                .filter_by(persona=persona) \
                .filter_by(active=True) \
                .filter_by(movement=self) \
                .first()

            rv = True if gms else False
        return rv

    def add_member(self, persona):
        """Add a Persona as member to this movement

        Args:
            persona (Persona): Persona object to be added
        """
        if persona not in self.members:
            self.members.append(persona)

    @cache.memoize(timeout=ATTENTION_CACHE_DURATION)
    def get_attention(self):
        """Return a numberic value indicating attention this Movement has received

        Returns:
            integer: Attention as a positive integer
        """
        timer = ExecutionTimer()

        thoughts = self.blog.index \
            .filter(content.Thought.state >= 0) \
            .filter(content.Thought.kind != "upvote").all()

        thoughts += self.mindspace.index \
            .filter(content.Thought.state >= 0) \
            .filter(content.Thought.kind != "upvote").all()

        rv = int(sum([t.hot() for t in thoughts]) * ATTENTION_MULT)
        timer.stop("Generated attention value for {}".format(self))
        return rv

    attention = property(get_attention)

    def authorize(self, action, author_id=None):
        """Return True if this Movement authorizes `action` for `author_id`

        Args:
            action (String): Action to be performed (see Synapse.ACCESS_MODES)
            author_id (String): Persona ID that wants to perform the action

        Returns:
            Boolean: True if authorized
        """
        rv = False
        if BaseModel.authorize(self, action, author_id=author_id):
            if action == "read":
                rv = True
                if self.private:
                    member = MovementMemberAssociation.query \
                        .filter_by(movement=self) \
                        .filter_by(active=True) \
                        .filter_by(persona_id=author_id) \
                        .first()

                    rv = member is not None
            else:
                rv = self.admin_id == author_id
        return rv

    @property
    def contacts(self):
        """Alias for Movememt.members for compatibility with Persona class"""
        return self.members.filter_by(active=True)

    def current_role(self):
        """Return role of the currently active Persona

        Returns:
            String: Name  of the role. One of "anonymous", "visitor",
                "member", "admin"
        """
        if not current_user or current_user.is_anonymous():
            rv = "anonymous"
        else:
            gma = MovementMemberAssociation.query.filter_by(movement_id=self.id). \
                filter_by(persona_id=current_user.active_persona.id).first()

            if gma is None:
                rv = "visitor"
            else:
                rv = gma.role
        return rv

    def get_absolute_url(self):
        """Return URL for this movement's mindspace page"""
        return url_for("web.movement", id=self.id)

    @cache.memoize(timeout=MEMBER_COUNT_CACHE_DURATION)
    def member_count(self):
        """Return number of active members in this movement

        Returns:
            int: member count
        """
        timer = ExecutionTimer()
        rv = MovementMemberAssociation.query \
            .filter_by(movement=self) \
            .filter_by(active=True) \
            .count()

        timer.stop("Generated member count for {}".format(self))
        return int(rv)

    @cache.memoize(timeout=MINDSPACE_TOP_THOUGHT_CACHE_DURATION)
    def mindspace_top_thought(self, count=15):
        """Return count top thoughts from mindspace

        Returns:
            list: Dicts with key 'id'
        """
        timer = ExecutionTimer()
        selection = self.mindspace.index.filter(content.Thought.state >= 0).all()
        rv = [t.id for t in sorted(
            selection, key=content.Thought.hot, reverse=True)[:count]]
        timer.stop("Generated {} mindspace top thought".format(self))
        return rv

    def promotion_check(self, thought):
        """Promote a Thought to this movement's blog if it has enough upvotes

        Args:
            thought (Thought): The thought to be promoted

        Returns:
            None: If no promotion was done
            Thought: The new blog post
        """
        rv = None
        if not thought._blogged and thought.mindset \
                and thought.mindset.kind == "mindspace":
            if thought.upvote_count() >= self.required_votes():
                logger.info("Promoting {} to {} blog".format(thought, self))
                clone = content.Thought.clone(thought, self, self.blog)
                upvote = content.Upvote(id=uuid4().hex,
                    author=self, parent=clone, state=0)
                clone.children.append(upvote)
                thought._blogged = True
                movement_chat.send(self, room_id=self.mindspace.id,
                    message="New promotion! Check the blog")
                rv = clone
        return rv

    def remove_member(self, persona):
        """Remove a Persona from this movement's local member list

        Args:
            persona (Persona): Persona object to be removed
        """
        if persona in self.members:
            self.members.remove(persona)

    def required_votes(self):
        """Return the number of votes required to promote a Thought ot the blog

        n = round(count/100 + 2/count + (log(1.65,count)))
        with count being the number of members this movement has

        Returns:
            int: Number of votes required
        """
        from math import log
        c = self.member_count()
        rv = int(c / 100.0 + 0.8 / c + log(c, 1.65)) if c > 0 else 1
        return rv

    @classmethod
    @cache.memoize(timeout=TOP_MOVEMENT_CACHE_DURATION)
    def top_movements(cls, count=10):
        """Return a list of top movements as measured by member count

        Returns:
            list: List of dicts with keys 'id', 'username'
        """
        timer = ExecutionTimer()
        movements = Movement.query \
            .join(MovementMemberAssociation) \
            .order_by(func.count(MovementMemberAssociation.persona_id)) \
            .group_by(MovementMemberAssociation.persona_id) \
            .group_by(Movement)

        rv = list()
        for m in movements.limit(count):
            rv.append({
                "id": m.id,
                "username": m.username
            })

        timer.stop("Generated top movements")
        return rv

    def voting_done(self, thought):
        """Provide a value in [0,1] indicating how many votes have been cast
            toward promoting a thought. For already blogged thoughts 1 is also
            returned

        Returns:
            float: Ratio of required votes already cast
        """
        if thought._blogged:
            rv = 1
        else:
            req = self.required_votes()
            rv = 1
            if req > 0:
                rv = min([float(thought.upvote_count()) /
                    self.required_votes(), 1.0])
        return rv
