# -*- coding: utf-8 -*-
"""
    nucleus.tests.test_content
    ~~~~~

    Test content models

    :copyright: (c) 2015 by Vincent Ahrend.
"""
import datetime
import pytest

from nucleus.nucleus.identity import Persona
from nucleus.nucleus.content import Thought, LinkPercept, TextPercept, \
    LinkedPicturePercept, ReplyNotification, MentionNotification, TagPercept


class TestThought():
    def test_model(self, thoughts):
        t = thoughts[1]
        assert isinstance(t.id, basestring)
        assert t.created < datetime.datetime.utcnow()
        assert t.modified < datetime.datetime.utcnow()
        assert t.kind == "thought"
        assert isinstance(t.author, Persona)
        assert isinstance(t.parent, Thought)
        assert len(t.percept_assocs) == 0
        assert isinstance(t.__repr__(), basestring)

    def test_authorize(self, thoughts, movements):
        t1 = thoughts[0]
        p1 = t1.author
        t1.mindset = p1.blog

        t2 = thoughts[2]
        p2 = t2.author
        t2.mindset = p2.mindspace

        assert t1.authorize("read", author_id=p1.id)
        assert t1.authorize("read", author_id=p2.id)
        assert not t2.authorize("read", author_id=p1.id)

        assert t1.authorize("delete", author_id=p1.id)
        assert not t1.authorize("delete", author_id=p2.id)

        m = movements[0]
        t3 = thoughts[1]
        t3.author = m
        t3.mindset = m.blog
        assert t3.authorize("update", author_id=m.id)
        assert t3.authorize("update", author_id=m.admin.id)

    def test_get_attachments(self, thought_with_attachments, persona):
        res = thought_with_attachments.get_attachments()
        assert isinstance(res["link"][0].percept, LinkPercept)
        assert isinstance(res["linkedpicture"][0].percept, LinkedPicturePercept)
        assert isinstance(res["text"][0].percept, TextPercept)

    def test_clone(self, thoughts):
        t1 = thoughts[0]
        p = thoughts[2].author
        t2 = Thought.clone(t1, p, p.mindspace)

        assert t2.id != t1.id
        assert t2.created > t1.created
        assert t1.text == t2.text
        assert t2.author == p
        assert t2.parent == t1
        assert t2.mindset == p.mindspace

        t1_percepts = [pa.percept for pa in t1.percept_assocs]
        for pa in t2.percept_assocs:
            assert pa not in t1.percept_assocs
            assert pa.author == p
            assert pa.percept in t1_percepts

    def test_comment_count(self, thoughts):
        assert thoughts[0].comment_count() == 1
        assert thoughts[1].comment_count() == 0

    def test_create_from_input(self, personas, session, thoughts):
        teststring = """Ok, so this is my #test for @{username}
        I have an image http://i.imgur.com/Yzv9H.jpg
        and a link http://i.imgur.com/Yzv9H/
        """.format(username=personas[1].username)

        parent = thoughts[2]
        author = personas[0]
        old_parent_comment_count = parent.comment_count()

        thought_data = Thought.create_from_input(
            author=author,
            text="Test title",
            longform=teststring,
            longform_source="source",
            mindset=author.blog,
            parent=parent)
        t = thought_data["instance"]

        assert parent.author != t.author

        session.add(t)
        session.commit()

        assert isinstance(t.created, datetime.datetime)
        assert isinstance(t.modified, datetime.datetime)
        assert t in author.blog
        assert isinstance(t.text, basestring)
        assert t.author == author
        assert t.parent is parent
        assert len(t.percept_assocs) == 5
        assert parent.comment_count() - 1 == old_parent_comment_count

        notifs = thought_data["notifications"]
        assert any(map(lambda x: isinstance(x, ReplyNotification), notifs))
        assert any(map(lambda x: isinstance(x, MentionNotification), notifs))

    def test_get_url(self, thoughts):
        assert thoughts[0].get_absolute_url().startswith("http")

    def test_has_text(self, thought_with_attachments, thoughts):
        assert thoughts[0].has_text() is False
        assert thought_with_attachments.has_text() is True

    def test_hot(self, thoughts, session):
        h1 = thoughts[0].hot(session=session)
        thoughts[0].toggle_upvote(
            author_id=thoughts[0].author.id, session=session)
        h2 = thoughts[0].hot(session=session)
        h3 = thoughts[0].hot(session=session)

        assert h1 == 0
        assert h1 < h2
        assert h3 < h2

    def test_update_comment_count(self, thoughts):
        t = thoughts[1]
        c1 = t.comment_count()
        c2 = t.parent.comment_count()

        t.update_comment_count(1)

        assert t.comment_count() == c1 + 1
        assert t.parent.comment_count() == c2 + 1

        with pytest.raises(ValueError):
            t.update_comment_count(1.5)

    def test_link_url(self, thoughts, thought_with_attachments):
        assert thought_with_attachments.link_url().startswith("http")
        assert thoughts[0].link_url() is None

    def test_get_tags(self, thought_with_attachments):
        res = thought_with_attachments.tags
        assert len(res) > 0
        assert isinstance(res[0], TagPercept)

    def test_top_thought(self, persona, movement_with_thoughts, session):
        t = movement_with_thoughts.mindspace.index.first()
        t.toggle_upvote(author_id=t.author.id, session=session)
        persona.follow_top_movements(session=session)

        for p in [None, persona]:
            res = Thought.top_thought(persona=p, session=session)
            assert len(res) >= 2
            assert isinstance(res[0], basestring)

            top = []
            for tid in res[:2]:
                top.append(session.query(Thought).get(tid))

            assert top[0].hot(session=session) > top[1].hot(session=session)

    def test_upvotes(self, thoughts, personas, session):
        thoughts[0].toggle_upvote(author_id=personas[0].id, session=session)
        assert thoughts[0].upvoted(author_id=personas[0].id, session=session)
        assert not thoughts[0].upvoted(author_id=personas[1].id, session=session)

    def test_get_upvotes(self, session, thoughts, personas):
        thoughts[0].toggle_upvote(author_id=personas[0].id, session=session)
        thoughts[0].toggle_upvote(author_id=personas[0].id, session=session)

        thoughts[0].toggle_upvote(author_id=personas[1].id, session=session)

        assert thoughts[0].get_upvotes(session=session).count() == 2

    def test_upvote_count(self, session, thoughts, personas):
        assert thoughts[0].upvote_count(session=session) == 0
        thoughts[0].toggle_upvote(author_id=personas[0].id, session=session)
        assert thoughts[0].upvote_count(session=session) == 1
        thoughts[0].toggle_upvote(author_id=personas[0].id, session=session)
        thoughts[0]._upvotes = None
        assert thoughts[0].upvote_count(session=session) == 0
