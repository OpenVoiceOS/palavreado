"""``detach_skill`` with no skill_id must remove nothing.

The handler filtered six collections with ``startswith(skill_id)``, and
``"".startswith`` is true for every name, so an empty payload removed
every skill's intents, gates, keywords, vocab and regexes.
"""
import unittest
from unittest import mock

from ovos_bus_client.message import Message

from palavreado.opm import PalavreadoPipeline


def _register(pipeline, skill_id, intent, keyword, word):
    pipeline.handle_register_vocab(Message(
        "register_vocab",
        {"entity_value": word, "entity_type": f"{skill_id}{keyword}", "lang": "en-US"},
        {"skill_id": skill_id}))
    pipeline.handle_register_intent(Message(
        "register_intent",
        {"name": f"{skill_id}:{intent}", "requires": [[f"{skill_id}{keyword}", f"{skill_id}{keyword}"]],
         "optional": [], "at_least_one": [], "excludes": []},
        {"skill_id": skill_id}))


class TestDetachSkillEmptyPayload(unittest.TestCase):

    def setUp(self):
        self.pipeline = PalavreadoPipeline(bus=mock.Mock(), config={})
        _register(self.pipeline, "a.skill", "one", "One", "alpha")
        _register(self.pipeline, "b.skill", "two", "Two", "beta")
        self.assertEqual(self._names(), {"a.skill:one", "b.skill:two"})

    def _names(self):
        return {i.get("name") for i in self.pipeline._registered_intents}

    def _match(self, utt):
        msg = Message("recognizer_loop:utterance", {"utterances": [utt], "lang": "en-US"})
        return self.pipeline.match_low([utt], "en-US", msg)

    def test_empty_payload_removes_nothing(self):
        with mock.patch("palavreado.opm.LOG.warning") as warn:
            self.pipeline.handle_detach_skill(Message("detach_skill", {}, {"skill_id": "a.skill"}))
        self.assertEqual(self._names(), {"a.skill:one", "b.skill:two"})
        self.assertEqual(len(self.pipeline.registered_vocab), 2)
        self.assertIsNotNone(self._match("alpha"))
        self.assertIsNotNone(self._match("beta"))
        self.assertTrue(any("skill_id" in c.args[0] for c in warn.call_args_list))

    def test_named_skill_is_removed_and_the_other_kept(self):
        self.pipeline.handle_detach_skill(Message("detach_skill", {"skill_id": "a.skill"}))
        self.assertEqual(self._names(), {"b.skill:two"})
        self.assertIsNone(self._match("alpha"))
        self.assertIsNotNone(self._match("beta"))
