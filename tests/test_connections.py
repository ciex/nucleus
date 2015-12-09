# -*- coding: utf-8 -*-
"""
    nucleus.tests.test_connections
    ~~~~~

    Test connections provided by Nucleus

    :copyright: (c) 2015 by Vincent Ahrend.
"""
from nucleus.nucleus.connections import session_scope, db, cache


def test_scoped_session():
    """Test whether scoped session can be created"""
    with session_scope() as session:
        assert hasattr(session, 'query')


def test_flask_session():
    """Test whether the Flask-SQLAlchemy session is created"""
    assert hasattr(db.session, 'query')


def test_cache(app):
    """Test whether the memcache can be used"""
    cache.set('test', True)
    assert cache.get('test') is True
    cache.delete('test')
