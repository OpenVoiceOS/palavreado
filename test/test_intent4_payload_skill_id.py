"""OVOS-INTENT-4 §3.2: the payload skill_id names the target.

"`context.skill_id` names the source that emitted the message (§3.1)
and is provenance only. A consumer — plugin or orchestrator — MUST act
on the payload value, MUST NOT substitute `context.skill_id` for it".

palavreado fell back to the context skill_id on every INTENT-4 handler
when the payload had none, so a deregister with no payload skill_id
removed the emitter's own intent.
"""
import unittest
from unittest import mock

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage

from palavreado.opm import PalavreadoPipeline

SKILL = "lighting.skill"
UTT = ["set brightness higher"]


class TestPayloadSkillIdOnly(unittest.TestCase):

    def setUp(self):
        self.pipeline = PalavreadoPipeline(bus=mock.Mock(), config={})
        self.pipeline.handle_register_keyword_intent(Message(
            str(SpecMessage.INTENT_REGISTER_KEYWORD), {
                "skill_id": SKILL, "intent_name": "set_brightness", "lang": "en-US",
                "required": [{"name": "set", "samples": ["set"]},
                             {"name": "brightness", "samples": ["brightness"]}],
                "optional": [], "one_of": [], "excluded": []},
            context={"skill_id": SKILL}))
        self.msg = Message("recognizer_loop:utterance",
                           {"utterances": UTT, "lang": "en-US"})
        self.assertIsNotNone(self.pipeline.match_low(UTT, "en-US", self.msg))

    def _matches(self):
        return self.pipeline.match_low(UTT, "en-US", self.msg) is not None

    def test_deregister_without_payload_skill_id_keeps_the_intent(self):
        self.pipeline.handle_intent_deregister(Message(
            str(SpecMessage.INTENT_DEREGISTER),
            {"skill_id": None, "intent_name": "set_brightness"},
            context={"skill_id": SKILL}))
        self.assertTrue(self._matches())

    def test_skill_deregister_without_payload_skill_id_keeps_the_intent(self):
        self.pipeline.handle_skill_deregister(Message(
            str(SpecMessage.SKILL_DEREGISTER), {}, context={"skill_id": SKILL}))
        self.assertTrue(self._matches())

    def test_disable_without_payload_skill_id_keeps_the_intent_armed(self):
        self.pipeline.handle_intent_disable(Message(
            str(SpecMessage.INTENT_DISABLE),
            {"intent_name": "set_brightness"}, context={"skill_id": SKILL}))
        self.assertTrue(self._matches())

    def test_enable_without_payload_skill_id_does_not_rearm(self):
        self.pipeline.handle_intent_disable(Message(
            str(SpecMessage.INTENT_DISABLE),
            {"skill_id": SKILL, "intent_name": "set_brightness"}))
        self.assertFalse(self._matches())
        self.pipeline.handle_intent_enable(Message(
            str(SpecMessage.INTENT_ENABLE),
            {"intent_name": "set_brightness"}, context={"skill_id": SKILL}))
        self.assertFalse(self._matches())

    def test_register_keyword_without_payload_skill_id_is_rejected(self):
        with mock.patch("palavreado.opm.LOG.warning") as warn:
            self.pipeline.handle_register_keyword_intent(Message(
                str(SpecMessage.INTENT_REGISTER_KEYWORD), {
                    "intent_name": "other", "lang": "en-US",
                    "required": [{"name": "kw", "samples": ["other"]}],
                    "optional": [], "one_of": [], "excluded": []},
                context={"skill_id": SKILL}))
        names = [i.get("name") for i in self.pipeline._registered_intents]
        self.assertNotIn(f"{SKILL}:other", names)
        self.assertTrue(any("skill_id" in c.args[0] for c in warn.call_args_list))

    def test_register_entity_without_payload_skill_id_is_rejected(self):
        with mock.patch("palavreado.opm.LOG.warning") as warn:
            self.pipeline.handle_register_entity(Message(
                str(SpecMessage.ENTITY_REGISTER),
                {"entity_name": "colour", "lang": "en-US", "samples": ["red"]},
                context={"skill_id": SKILL}))
        self.assertFalse(any(v.get("entity_type") == "colour"
                             for v in self.pipeline.registered_vocab))
        self.assertTrue(any("skill_id" in c.args[0] for c in warn.call_args_list))

    def test_payload_target_differs_from_context_source_is_honoured(self):
        # §3.2: a difference is not grounds for rejection; the payload wins
        self.pipeline.handle_intent_deregister(Message(
            str(SpecMessage.INTENT_DEREGISTER),
            {"skill_id": SKILL, "intent_name": "set_brightness"},
            context={"skill_id": "other.skill"}))
        self.assertFalse(self._matches())


class TestSkillDeregisterOverTheBus(unittest.TestCase):
    """The live case: a bus client dispatches ``ovos.skill.deregister`` to its
    counterpart topic ``detach_skill`` with the same payload, so the §8.4
    handler's rejection is not enough. ``handle_detach_skill`` must reject an
    empty target too, or the counterpart wipes every skill."""

    LIGHTS = "lights.harness"
    MUSIC = "music.harness"

    def setUp(self):
        from ovos_utils.fakebus import FakeBus
        self.bus = FakeBus()
        self.pipeline = PalavreadoPipeline(bus=self.bus, config={})
        self._register(self.LIGHTS, "lights_on", ["turn on", "lights"])
        self._register(self.MUSIC, "play_music", ["play", "music"])
        self.assertEqual(self._names(), {f"{self.LIGHTS}:lights_on",
                                         f"{self.MUSIC}:play_music"})
        self.assertIsNotNone(self._match("turn on the lights"))
        self.assertIsNotNone(self._match("play some music"))

    def _register(self, skill_id, intent, words):
        self.bus.emit(Message(
            str(SpecMessage.INTENT_REGISTER_KEYWORD), {
                "skill_id": skill_id, "intent_name": intent, "lang": "en-US",
                "required": [{"name": w.replace(" ", "_"), "samples": [w]}
                             for w in words],
                "optional": [], "one_of": [], "excluded": []},
            context={"skill_id": skill_id}))

    def _names(self):
        return {i.get("name") for i in self.pipeline._registered_intents}

    def _match(self, utt):
        msg = Message("recognizer_loop:utterance",
                      {"utterances": [utt], "lang": "en-US"})
        return self.pipeline.match_low([utt], "en-US", msg)

    def test_empty_skill_deregister_over_the_bus_keeps_both_skills(self):
        seen = []
        self.bus.on("detach_skill", lambda m: seen.append(m.data))
        with mock.patch("palavreado.opm.LOG.warning") as warn:
            self.bus.emit(Message(str(SpecMessage.SKILL_DEREGISTER), {},
                                  context={"skill_id": self.MUSIC}))
        self.assertEqual(seen, [{}], "control: the counterpart topic was "
                                     "dispatched with the same empty payload")
        self.assertEqual(self._names(), {f"{self.LIGHTS}:lights_on",
                                         f"{self.MUSIC}:play_music"})
        self.assertIsNotNone(self._match("turn on the lights"))
        self.assertIsNotNone(self._match("play some music"))
        rejected = [c.args[0] for c in warn.call_args_list
                    if c.args[0].startswith("rejected")]
        self.assertEqual(len(rejected), 2, rejected)

    def test_named_skill_deregister_over_the_bus_removes_only_that_skill(self):
        self.bus.emit(Message(str(SpecMessage.SKILL_DEREGISTER),
                              {"skill_id": self.LIGHTS},
                              context={"skill_id": self.MUSIC}))
        self.assertEqual(self._names(), {f"{self.MUSIC}:play_music"})
        self.assertIsNone(self._match("turn on the lights"))
        self.assertIsNotNone(self._match("play some music"))
