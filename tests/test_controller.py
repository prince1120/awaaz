import pytest
from app.controller import (
    select_speakers_for_turn,
    detect_addressed_personas,
    check_interruption_intent,
    VOICE_CATALOG
)
from app.session import GroupDiscussionSession


def test_explicit_addressing_single():
    speakers = select_speakers_for_turn("What do you think Manager?")
    assert "manager" in speakers
    assert speakers[0] == "manager"

    speakers_friend = select_speakers_for_turn("Hey Sunny, give me an idea!")
    assert "friend" in speakers_friend

    speakers_boy = select_speakers_for_turn("What do you think Boy?")
    assert "friend" in speakers_boy

    speakers_shiro = select_speakers_for_turn("Shiro, where should we travel?")
    assert "saheli" in speakers_shiro

    speakers_mom = select_speakers_for_turn("Mom, what should I eat?")
    assert "mom" in speakers_mom

    speakers_dad = select_speakers_for_turn("Dad, should I take this investment?")
    assert "dad" in speakers_dad

    speakers_tech = select_speakers_for_turn("Kalpit, will this architecture scale?")
    assert "tech_lead" in speakers_tech


def test_explicit_addressing_multi():
    speakers = select_speakers_for_turn("Mom and Dad, what do you both think?")
    assert "mom" in speakers
    assert "dad" in speakers


def test_open_brainstorming_topic_routing():
    # Tech question routes to tech_lead
    speakers = select_speakers_for_turn("How do we optimize Python API latency and microservices?")
    assert "tech_lead" in speakers

    # Budget question in office room routes to manager
    speakers = select_speakers_for_turn("We need to cut budget and meet the quarterly deadline.", room_id="office")
    assert "manager" in speakers

    # Health/food routes to mom
    speakers = select_speakers_for_turn("I feel tired and have a bad headache today.", room_id="family")
    assert "mom" in speakers


def test_interruption_detection():
    assert check_interruption_intent("stop talking please") is True
    assert check_interruption_intent("ruko ek minute") is True
    assert check_interruption_intent("chup raho") is True
    assert check_interruption_intent("that sounds like a brilliant plan") is False


def test_dual_layer_memory():
    sess = GroupDiscussionSession("test_roundtable")
    
    # User speaks
    sess.add_user_speech("Let's build a voice AI startup.")
    assert len(sess.global_history) == 1
    
    # Manager speaks
    sess.add_persona_speech("manager", "We need a clear business plan and timeline.")
    assert len(sess.global_history) == 2
    assert len(sess.local_memory["manager"]) == 1
    assert "timeline" in sess.local_memory["manager"][0]
    
    # Friend speaks
    sess.add_persona_speech("friend", "Bro, let's call it Awaaz and make it hilarious!")
    assert len(sess.global_history) == 3
    assert len(sess.local_memory["friend"]) == 1
    
    # When building prompt for Tech Lead, they see what User, Manager, and Friend said
    tech_msgs = sess.build_persona_llm_messages("tech_lead")
    rendered_history = " ".join(m["content"] for m in tech_msgs)
    assert "Manager" in rendered_history
    assert "Sunny" in rendered_history or "Friend" in rendered_history or "Awaaz" in rendered_history
    
    # Session reset purges both global and local memory
    sess.clear()
    assert len(sess.global_history) == 0
    assert len(sess.local_memory["manager"]) == 0
    assert len(sess.local_memory["friend"]) == 0
