from freezegun import freeze_time
from datetime import datetime

from django.apps import apps
from django.test import TestCase
from django.conf import settings

from django_elect import settings
from django_elect.models import Ballot, Candidate, Election, Vote, \
    VotePlurality, VotePreferential


@freeze_time("2010-10-10 00:00:00")
class VoteTestCase(TestCase):
    """
    Tests for the vote() view that don't depend on ballots
    """
    urls = 'django_elect.tests.urls'

    def test_when_voting_unallowed(self):
        # should get redirected when not logged in
        response = self.client.get("/election/")
        self.assertRedirects(response, settings.LOGIN_URL + "?next=/election/")

        # should get a 404 if no election exists
        user_model = apps.get_model(settings.DJANGO_ELECT_USER_MODEL)
        user1 = user_model.objects.create_user(username="foo@bar.com",
            email='foo@bar.com', password="foo")
        self.client.login(username="foo@bar.com", password="foo")
        response = self.client.get("/election/")
        self.assertEqual(response.status_code, 404)

        # should get redirected if election exists but not active
        past_election = Election.objects.create(
            name="finished",
            vote_start=datetime(2010, 10, 1),
            vote_end=datetime(2010, 10, 9))
        past_election.allowed_voters.add(user1)
        response = self.client.get("/election/")
        self.assertRedirects(response, settings.LOGIN_URL)

        future_election = Election.objects.create(
            name="future",
            vote_start=datetime(2010, 10, 11),
            vote_end=datetime(2010, 10, 17))
        future_election.allowed_voters.add(user1)
        response = self.client.get("/election/")
        self.assertRedirects(response, settings.LOGIN_URL)

        # should get redirected if election exists and is active, not voter
        # not in allowed_voters
        current_election = Election.objects.create(
            name="current",
            vote_start=datetime(2010, 10, 1),
            vote_end=datetime(2010, 10, 11))
        response = self.client.get("/election/")
        self.assertRedirects(response, settings.LOGIN_URL)


@freeze_time("2010-10-10 00:00:00")
class BaseBallotVoteTestCase(TestCase):
    """
    Base class for testing the vote() view using specific ballots
    """
    urls = 'django_elect.tests.urls'

    def run(self, result=None):
        if not hasattr(self, "ballot_type"):
            return
        return super(BaseBallotVoteTestCase, self).run(result)

    def setUp(self):
        """
        Initializes an active election with two ballots of the specified type.
        First ballot is secret and has 2 seats available w/ 4 candidates.
        Second isn't secret and has 4 seats available w/ 6 candidate.
        """
        user_model = apps.get_model(settings.DJANGO_ELECT_USER_MODEL)
        self.user1 = user_model.objects.create_user(username="foo@bar.com",
            email='foo@bar.com', password="foo")
        self.client.login(username="foo@bar.com", password="foo")
        self.election = Election.objects.create(
            name="current",
            vote_start=datetime(2010, 10, 1),
            vote_end=datetime(2010, 10, 11))
        self.election.allowed_voters.add(self.user1)

        ballot1 = self.election.ballots.create(id=1, type=self.ballot_type,
            seats_available=2, is_secret=True, write_in_available=True,
            introduction="something something")
        for i in range(1, 5):
            ballot1.candidates.create(id=Candidate.objects.count() + 1,
                first_name="Ballot 1", last_name="Candidate %i" % i)

        ballot2 = self.election.ballots.create(id=2, type=self.ballot_type,
            seats_available=4, is_secret=False, write_in_available=False)
        for i in range(1, 7):
            ballot2.candidates.create(id=Candidate.objects.count() + 1,
                first_name="Ballot 2", last_name="Candidate %i" % i)

    def test_generic(self):
        """
        Does tests that are independent of the ballot type.
        This is a separate method so it can be called by both
        test_with_plurality() and test_with_preferential()
        """
        ballot_type = self.ballot_type
        # vote page should have ballot introduction and the names for
        # all candidates
        response = self.client.get("/election/")
        self.assertContains(response, "something something", 1)
        for b in self.election.ballots.all():
            for c in b.candidates.all():
                self.assertContains(response, c.get_name())

        # vote page should NOT list any write-in candidates
        cand = Candidate.objects.create(ballot=self.election.ballots.all()[0],
            first_name="Ralph", last_name="Nader", write_in=True)
        self.assertNotContains(response, cand.get_name())
        cand.delete()

        # first ballot should have write-in field, second shouldn't
        self.assertContains(response, 'id="id_ballot1-write_in_1"')
        self.assertNotContains(response, 'id="id_ballot2-write_in_1"')

        # shouldn't be allowed to submit a vote without selecting a candidate
        response = self.client.post("/election/")
        self.assertEqual(response.status_code, 200)


class PluralityVoteTestCase(BaseBallotVoteTestCase):
    """
    Tests the vote() view when election consists of plurality ballots.
    """
    ballot_type = "Pl"

    def setUp(self):
        """
        Add 2 more ballots, both with 1 seat available and 2 candidates, one
        with write-in and one without, to test radio widget functionality.
        """
        super(PluralityVoteTestCase, self).setUp()
        ballot3 = self.election.ballots.create(id=3, type=self.ballot_type,
            seats_available=1, is_secret=False, write_in_available=False)
        for i in range(1, 3):
            ballot3.candidates.create(id=Candidate.objects.count() + 1,
                first_name="Ballot 3", last_name="Candidate %i" % i)

        ballot4 = self.election.ballots.create(id=4, type=self.ballot_type,
            seats_available=1, is_secret=False, write_in_available=True)
        for i in range(1, 3):
            ballot4.candidates.create(id=Candidate.objects.count() + 1,
                first_name="Ballot 4", last_name="Candidate %i" % i)

    def test_excessive_selections(self):
        # shouldn't be allowed to submit a vote for more candidates than
        # seats available
        data = ['ballot1-1', 'ballot1-2', 'ballot1-3']
        response = self.client.post("/election/", dict.fromkeys(data, "on"))
        self.assertContains(response, 'id="error0"')

        data += ['ballot2-6', 'ballot2-7']
        response = self.client.post("/election/", dict.fromkeys(data, "on"))
        self.assertContains(response, 'id="error0"')

        data = data[3:] + ['ballot2-8', 'ballot2-9', 'ballot2-10']
        response = self.client.post("/election/", dict.fromkeys(data, "on"))
        self.assertContains(response, 'id="error0"')

        # write-in candidates should count towards seat availability check
        response = self.client.post("/election/", {
            'ballot1-1': "on",
            'ballot1-2': "on",
            'ballot1-write_in_0': "Jade",
            'ballot1-write_in_1': "Stern",
        })
        self.assertContains(response, 'id="error0"')

        response = self.client.post("/election/", {
            'ballot4-write_in_0': 'Jade',
            'ballot4-write_in_1': 'Stern',
            'ballot4-13': 'on',
        })
        self.assertContains(response, 'id="error0"')

    def test_single_selection(self):
        # should be able to vote by just checking one candidate
        response = self.client.post("/election/", {'ballot1-1': 'on'})
        self.assertRedirects(response, "/election/success")

        # first ballot is secret, so only the fact that the voter voted
        # should have been recorded
        vote_objects = Vote.objects.all()
        self.assertEqual(vote_objects.count(), 1)
        self.assertEqual(vote_objects[0].account, self.user1)
        vpl_objects = VotePlurality.objects.all()
        self.assertEqual(vpl_objects.count(), 1)
        self.assertTrue(vpl_objects[0].vote is None)

    def test_invalid_writein(self):
        # write-in field should require both first and last names
        response = self.client.post("/election/", {
            'ballot1-write_in_0': "Jade",
            'ballot1-write_in_1': "",
        })
        self.assertContains(response, 'id="error0"')

    def test_only_writein(self):
        # should be able to vote by just filling in a write-in candidate
        write_in_data = {
            'ballot1-write_in_0': "Jade",
            'ballot1-write_in_1': "Stern",
            'ballot4-write_in_0': "Hina",
            'ballot4-write_in_1': "Ichigo",
        }
        response = self.client.post("/election/", write_in_data)
        self.assertRedirects(response, "/election/success")
        new_candidate = Candidate.objects.get(first_name="Jade")
        new_candidate2 = Candidate.objects.get(first_name="Hina")
        self.assertTrue(new_candidate.write_in)
        self.assertTrue(new_candidate2.write_in)

    def test_complete_ballot(self):
        # should be able to vote by selecting the same # of candidates as the
        # # of seats available
        data = {
            'ballot1-write_in_0': "Jade",
            'ballot1-write_in_1': "Stern",
            'ballot1-1': 'on',
            'ballot2-7': 'on',
            'ballot2-8': 'on',
            'ballot2-9': 'on',
            'ballot2-10': 'on',
            'ballot3': 'ballot3-12',
            'ballot4-14': 'on',
        }
        response = self.client.post("/election/", data)
        self.assertRedirects(response, "/election/success")

        vote_objects = Vote.objects.filter(account=self.user1)
        self.assertEqual(vote_objects.count(), 1)

        # check for vote secrecy again for first ballot
        first_ballot = self.election.ballots.get(id=1)
        vpl_objects = VotePlurality.objects.filter(
            candidate__ballot=first_ballot)
        self.assertEqual(vpl_objects.count(), 2)
        for vpl in vpl_objects:
            self.assertTrue(vpl.vote is None)

        second_ballot = self.election.ballots.get(id=2)
        vpl_objects = VotePlurality.objects.filter(
            candidate__ballot=second_ballot)
        self.assertEqual(vpl_objects.count(), 4)
        for vpl in vpl_objects:
            self.assertEqual(vpl.vote, vote_objects[0])

        third_ballot = self.election.ballots.get(id=3)
        fourth_ballot = self.election.ballots.get(id=4)
        for ballot in [third_ballot, fourth_ballot]:
            vpl_objects = VotePlurality.objects.filter(
                candidate__ballot=ballot)
            self.assertEqual(vpl_objects.count(), 1)
            for vpl in vpl_objects:
                self.assertEquals(vpl.vote, vote_objects[0])


class PreferentialVoteTestCase(BaseBallotVoteTestCase):
    """
    Tests the vote() view when the election consists of preferential ballots.
    """
    ballot_type = "Pr"
    b1_post_fields = ['ballot1-1', 'ballot1-2', 'ballot1-3', 'ballot1-4']
    b2_post_fields = ['ballot2-5', 'ballot2-6', 'ballot2-7', 'ballot2-8',
        'ballot2-9', 'ballot2-10']

    def test_with_invalid_points(self):
        # shouldn't allow invalid point values (i.e. where point < 0 or
        # point > # of candidates)
        b2_post_data = dict.fromkeys(self.b2_post_fields, "0").items()
        b1_post_data = zip(self.b1_post_fields, ["5", "2", "1", "0"])
        post_data = b1_post_data + b2_post_data
        response = self.client.post("/election/", dict(post_data))
        self.assertContains(response, 'id="error0"')

        b1_post_data = zip(self.b1_post_fields, ["999", "2", "1", "-999"])
        post_data = b1_post_data + b2_post_data
        response = self.client.post("/election/", dict(post_data))
        self.assertContains(response, 'id="error0"')

    def test_with_duplicate_points(self):
        # duplicate point values shouldn't be allowed (except for 0)
        b2_post_data = dict.fromkeys(self.b2_post_fields, "0").items()
        b1_post_data = zip(self.b1_post_fields, ["2", "2", "1", "0"])
        post_data = b1_post_data + b2_post_data
        response = self.client.post("/election/", dict(post_data))
        self.assertContains(response, 'id="error0"')

        b1_post_data = zip(self.b1_post_fields, ["1", "2", "1", "1"])
        post_data = b1_post_data + b2_post_data
        response = self.client.post("/election/", dict(post_data))
        self.assertContains(response, 'id="error0"')

    def test_with_duplicate_zeros(self):
        b2_post_data = dict.fromkeys(self.b2_post_fields, "0").items()
        b1_post_data = zip(self.b1_post_fields, ["1", "2", "0", "0"])
        post_data = b1_post_data + b2_post_data
        response = self.client.post("/election/", dict(post_data))
        self.assertRedirects(response, "/election/success")

    def test_with_invalid_writein(self):
        # write-in field should require both first and last names and that
        # the point drop-down be non-zero
        write_in_data = {
            'ballot1-write_in_0': '0',
            'ballot1-write_in_1': "Ralph",
            'ballot1-write_in_2': "Nader",
        }
        fields = self.b1_post_fields + self.b2_post_fields
        post_data = dict.fromkeys(fields, "0")
        post_data.update(write_in_data)
        response = self.client.post("/election/", post_data)
        self.assertContains(response, 'id="error0"')

        post_data['ballot1-write_in_0'] = '2'
        post_data['ballot1-write_in_2'] = ''
        response = self.client.post("/election/", post_data)
        self.assertContains(response, 'id="error0"')

    def test_with_only_writen(self):
        # should be able to vote by just filling in a write-in candidate
        write_in_data = {
            'ballot1-write_in_0': '2',
            'ballot1-write_in_1': "Ralph",
            'ballot1-write_in_2': "Nader",
        }
        fields = self.b1_post_fields + self.b2_post_fields
        post_data = dict.fromkeys(fields, "0")
        post_data.update(write_in_data)
        response = self.client.post("/election/", post_data)
        self.assertRedirects(response, "/election/success")

        new_candidate = Candidate.objects.get(first_name="Ralph")
        self.assertTrue(new_candidate.write_in)

        first_ballot = self.election.ballots.get(is_secret=True)
        vpr_objects = VotePreferential.objects.filter(
            candidate__ballot=first_ballot)
        self.assertEqual(vpr_objects.count(), 1)
        self.assertEqual(vpr_objects[0].point, 2)

    def test_with_single_point(self):
        # should be able to vote by having only one candidate with more
        # than 0 points
        fields = self.b1_post_fields + self.b2_post_fields
        post_data = dict.fromkeys(fields, "0")
        post_data['ballot1-1'] = '3'
        response = self.client.post("/election/", post_data)
        self.assertRedirects(response, "/election/success")

        vote_objects = Vote.objects.filter(account=self.user1)
        self.assertEqual(vote_objects.count(), 1)
        self.assertEqual(vote_objects[0].account, self.user1)

        vpr_objects = VotePreferential.objects.all()
        self.assertEqual(vpr_objects.count(), 1)
        self.assertEqual(vpr_objects[0].point, 3)
        self.assertTrue(vpr_objects[0].vote is None)

    def test_complete_ballot(self):
        # now try doing a proper vote
        fields = self.b1_post_fields + self.b2_post_fields
        post_data = dict.fromkeys(fields, "0")
        modifications = {
            'ballot1-write_in_0': '2',
            'ballot1-write_in_1': "Ralph",
            'ballot1-write_in_2': "Nader",
            'ballot1-1': '4',
            'ballot1-2': '3',
            'ballot1-3': '0',
            'ballot1-4': '1',
            'ballot2-5': '0',
            'ballot2-6': '5',
            'ballot2-7': '4',
            'ballot2-8': '3',
            'ballot2-9': '6',
            'ballot2-10': '2',
        }
        post_data.update(modifications)
        response = self.client.post("/election/", post_data)
        self.assertRedirects(response, "/election/success")

        vote_objects = Vote.objects.filter(account=self.user1)
        self.assertEqual(vote_objects.count(), 1)

        # check for vote secrecy again for first ballot
        first_ballot = self.election.ballots.get(is_secret=True)
        vpr_objects = VotePreferential.objects.filter(
            candidate__ballot=first_ballot)
        self.assertEqual(vpr_objects.count(), 4)
        self.assertEqual(vpr_objects.get(candidate__id=1).point, 4)
        self.assertEqual(vpr_objects.get(candidate__id=2).point, 3)
        self.assertEqual(vpr_objects.get(candidate__id=4).point, 1)
        new_candidate = Candidate.objects.get(first_name="Ralph")
        self.assertEqual(vpr_objects.get(candidate=new_candidate).point, 2)

        # now do second ballot
        second_ballot = self.election.ballots.get(is_secret=False)
        vpr_objects = VotePreferential.objects.filter(
            candidate__ballot=second_ballot)
        self.assertEqual(vpr_objects.count(), 5)
        self.assertEqual(vpr_objects.get(candidate__id=6).point, 5)
        self.assertEqual(vpr_objects.get(candidate__id=7).point, 4)
        self.assertEqual(vpr_objects.get(candidate__id=8).point, 3)
        self.assertEqual(vpr_objects.get(candidate__id=9).point, 6)
        self.assertEqual(vpr_objects.get(candidate__id=10).point, 2)
