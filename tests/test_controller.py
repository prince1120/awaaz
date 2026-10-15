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


def test_multi_agent_explicit_ordering():
    # User addresses Rohan and Dev
    office_order_1 = select_speakers_for_turn("Rohan and Dev, what do you think?", room_id="office")
    assert office_order_1 == ["manager", "tech_lead"]

    # User addresses Dev and Rohan (reversed order)
    office_order_2 = select_speakers_for_turn("Dev and Rohan, can we ship this?", room_id="office")
    assert office_order_2 == ["tech_lead", "manager"]

    # Chill room both speakers
    chill_order = select_speakers_for_turn("Sunny and Shiro, let's plan a trip", room_id="chill")
    assert chill_order == ["friend", "saheli"]

    # Family room both speakers
    family_order = select_speakers_for_turn("Mom and Dad, what should I do?", room_id="family")
    assert family_order == ["mom", "dad"]

    # Generic 'both of you'
    both_office = select_speakers_for_turn("What do both of you think?", room_id="office")
    assert both_office == ["manager", "tech_lead"]

    # Hindi 'dono'
    dono_family = select_speakers_for_turn("Dono batao kya sahi rahega?", room_id="family")
    assert dono_family == ["mom", "dad"]


def test_peer_referral_detection():
    from app.controller import detect_peer_referral

    # Rohan invites Dev
    ref1 = detect_peer_referral("Dev, what's your technical assessment on the database latency?", "manager", "office")
    assert ref1 == "tech_lead"

    # Dev references Rohan
    ref2 = detect_peer_referral("Rohan, can we fit this into sprint 3?", "tech_lead", "office")
    assert ref2 == "manager"

    # Sunny references Shiro
    ref3 = detect_peer_referral("Shiro, remember that cafe in Old Goa?", "friend", "chill")
    assert ref3 == "saheli"

    # Shiro references Sunny
    ref4 = detect_peer_referral("Sunny, that sounds like a crazy idea!", "saheli", "chill")
    assert ref4 == "friend"

    # Mom references Dad
    ref5 = detect_peer_referral("Mahesh ji, aap bhi samjhaiye ise.", "mom", "family")
    assert ref5 == "dad"

    # Dad references Mom
    ref6 = detect_peer_referral("Shalini theek keh rahi hai, health pe pehle dhyan do.", "dad", "family")
    assert ref6 == "mom"

    # Unrelated statement should not trigger peer referral
    ref_none = detect_peer_referral("The quarterly results look promising and steady.", "manager", "office")
    assert ref_none is None


def test_multi_agent_turn_context_prompting():
    sess = GroupDiscussionSession("test_context_session")
    sess.set_room("office")
    sess.add_user_speech("Dev and Rohan, how do we reduce latency?")
    sess.add_persona_speech("tech_lead", "We should use HTTP/2 streaming and Redis caching.")

    # Second speaker (Rohan) speaks with turn_context referencing Dev
    turn_ctx = {
        "is_multi_turn_second_speaker": True,
        "preceding_speaker_id": "tech_lead",
        "preceding_speaker_name": "Tech Lead (Dev)",
        "preceding_short_name": "Dev",
        "preceding_turn_text": "We should use HTTP/2 streaming and Redis caching.",
        "addressed_by_peer": False,
    }

    msgs = sess.build_persona_llm_messages("manager", turn_context=turn_ctx)
    system_text = msgs[0]["content"]

    # Verify that prompt instructs referencing Dev by name
    assert "MULTI-AGENT SEQUENTIAL ROUNDTABLE TURN" in system_text
    assert "Dev" in system_text
    assert "reference" in system_text.lower()


def test_clause_segmentation():
    from app.main import should_split_clause

    # Short incomplete phrase should not split
    assert should_split_clause("Hello") is False

    # Terminal punctuation on >= 3 words splits cleanly
    assert should_split_clause("Sure thing, Ken.") is True
    assert should_split_clause("Haan bilkul, Shiro!") is True
    assert should_split_clause("What do you think?") is True

    # Comma should NOT split mid-sentence (preserves natural prosody)
    assert should_split_clause("Looking at the system architecture,") is False
    assert should_split_clause("Sunny is right, yaar,") is False

    # Fallback threshold for long clauses without punctuation
    long_clause = "This is a continuous stream of words without any punctuation mark at all to test length threshold and prevent buffer overrun"
    assert should_split_clause(long_clause) is True
