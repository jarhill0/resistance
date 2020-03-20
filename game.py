from enum import Enum, auto
from random import sample
from random import randint


class GameStates(Enum):
    NOT_STARTED = auto()
    NOMINATING = auto()
    VOTING_MISSION = auto()
    RUNNING_MISSION = auto()
    GAME_OVER = auto()


class Game:
    def __init__(self, connections):
        self.connections = connections  # mutable reference outside of this scope.
        self.players = ()  # should be immutable or owned by this class
        self.state = GameStates.NOT_STARTED
        self.spies = None
        self.mission_leader = None
        self.round_num = 0
        self.successes = 0
        self.mission = None
        self.nom_votes = dict()
        self.mission_votes = dict()
        self.nominations_rejected = 0

        self.STATES = {
            GameStates.NOT_STARTED: self.not_started,
            GameStates.NOMINATING: self.nominating,
            GameStates.VOTING_MISSION: self.voting_mission,
            GameStates.RUNNING_MISSION: self.running_mission,
            GameStates.GAME_OVER: self.game_is_over,
        }

    async def player_move(self, player_id, move):
        handler = self.STATES[self.state]
        await handler(player_id, move)

    async def not_started(self, player_id, move):
        kind = move.get("kind")
        if kind == "start":
            await self.start()

    async def game_is_over(self):
        pass

    async def broadcast(self, message):
        for client, _ in self.connections:
            await client.put(message)

    def can_join(self, player_id):
        if self.state == GameStates.NOT_STARTED:
            return True
        else:
            return player_id in self.players

    async def start(self):
        self.players = tuple(set(name for _, name in self.connections))

        if not (5 <= len(self.players) <= 10):
            return  # TODO: handle

        self.choose_mission_leader()
        self.make_roles()

        base_message = {
            "kind": "game_start",
            "players": self.players,
            "num_players": len(self.players),
            "num_spies": len(self.spies),
            "agents_per_round": NUM_AGENTS_DICT[len(self.players)],
        }
        spy_message = dict(is_spy=True, spies=self.spies, **base_message,)
        resistance_message = dict(is_spy=False, **base_message)
        for connection, player_id in self.connections:
            if player_id in self.spies:
                await connection.put(spy_message)
            else:
                await connection.put(resistance_message)
        await self.start_round()

    async def start_round(self):
        self.nominations_rejected = 0
        await self.broadcast(
            {
                "kind": "round_start",
                "mission_size": self.mission_size(),
                "mission_number": self.round_num,
            }
        )
        await self.start_nomination()

    async def start_nomination(self):
        mission_leader = self.players[self.mission_leader]
        self.state = GameStates.NOMINATING
        await self.broadcast(
            {
                "kind": "nomination_start",
                "mission_leader": mission_leader,
                "vote_track": self.nominations_rejected,
            }
        )

    async def nominating(self, player_id, move):
        if (
            move.get("kind") == "nominate"
            and player_id == self.players[self.mission_leader]
        ):
            nominated_mission = move.get("nomination")
            if self.validate_mission(nominated_mission):
                self.state = GameStates.VOTING_MISSION
                self.update_mission_leader()
                self.nom_votes.clear()
                self.mission = nominated_mission
                await self.broadcast(
                    {
                        "kind": "mission_nominated",
                        "mission": nominated_mission,
                        "mission_leader": player_id,
                    }
                )

    async def voting_mission(self, player_id, move):
        if move.get("kind") == "nomination_vote":
            self.nom_votes[player_id] = bool(move.get("vote"))
            if len(self.nom_votes) == len(self.players):
                await self.process_votes()

    async def process_votes(self):
        # TODO what if we're processing votes and another comes in? Somehow we need to lock.
        approved = self.mission_approved(sum(self.nom_votes.values()))
        await self.broadcast(
            {
                "kind": "nomination_vote_results",
                "results": self.nom_votes,
                "approved": approved,
                "vote_track": self.nominations_rejected,
            }
        )
        if approved:
            self.state = GameStates.RUNNING_MISSION
            await self.start_mission()
        else:
            self.nominations_rejected += 1
            if self.nominations_rejected == 5:
                await self.broadcast(
                    {"kind": "game_over", "resistance_won": False, "spies": self.spies,}
                )
            else:
                await self.start_nomination()

    async def start_mission(self):
        self.mission_votes.clear()
        await self.broadcast({"kind": "mission_start", "mission": self.mission})

    async def running_mission(self, player_id, move):
        if move.get("kind") == "mission_vote" and player_id in self.mission:
            self.mission_votes[player_id] = bool(move.get("vote"))
            if len(self.mission_votes) == len(self.mission):
                await self.process_mission()

    async def process_mission(self):
        num_fails = sum(1 for vote in self.mission_votes.values() if not vote)
        mission_succeeded = self.mission_succeeds(num_fails)
        await self.broadcast(
            {
                "kind": "mission_result",
                "mission_number": self.round_num,
                "mission_succeeded": mission_succeeded,
                "num_fails": num_fails,
            }
        )
        if mission_succeeded:
            self.successes += 1
        if self.game_over():
            await self.broadcast(
                {
                    "kind": "game_over",
                    "resistance_won": self.resistance_won(),
                    "spies": list(self.spies),
                }
            )
            self.state = GameStates.GAME_OVER
        else:
            self.round_num += 1
            await self.start_round()

    def make_roles(self):
        """Assign roles to players."""
        num_roles = len(self.players)

        if num_roles == 5 or 6:
            num_spies = 2
        elif num_roles == 7 or 8:
            num_spies = 3
        else:
            num_spies = 4

        self.spies = sample(self.players, k=num_spies)

    def choose_mission_leader(self):
        """Randomly select a player to be the first mission leader."""
        num_players = len(self.players)
        self.mission_leader = randint(0, num_players - 1)

    def mission_size(self):
        """Determine the number of people on the current mission."""
        num_players = len(self.players)
        return NUM_AGENTS_DICT[num_players][self.round_num]

    def validate_mission(self, mission):
        """
        Check that a possible mission is valid.

        Specifically, it must:
          - have type list
          - have the length appropriate for the current mission size
          - have unique members who are all players of this game
        """

        if type(mission) is not list or len(mission) != self.mission_size():
            return False
        for i in mission:
            if i not in self.players:
                return False
        return len(set(mission)) == len(mission)

    def update_mission_leader(self):
        """Update who the mission leader is."""
        num_players = len(self.players)
        if self.mission_leader == num_players - 1:
            self_mission_leader = 0
        else:
            self.mission_leader += 1

    def mission_approved(self, num_approve):
        """Check if a mission is approved."""
        num_players = len(self.players)
        return num_approve > num_players / 2

    def mission_succeeds(self, num_fails):
        """Check if a mission succeeds."""
        return num_fails <= self.max_fails()

    def max_fails(self):
        """Get the maximum allowed number of fails for the current round."""
        num_players = len(self.players)
        if num_players >= 7 and self.round_num == 3:
            # done? (Elizabeth): Use self.round_num and num_players to determine the maximum number of fails allowed.
            # done? -----------: This number is usually 0, except in large games in the fourth round.
            return 1
        else:
            return 0

    def game_over(self):
        """Check if the game is over."""
        fails = self.round_num - self.successes + 1
        if self.round_num == 4:
            return True
        return self.successes == 3 or fails == 3

    def resistance_won(self):
        """Check if the resistance won. Assume the game is over."""
        # TODO (Elizabeth): Use self.successes to determine if the resistance won or not.
        return self.successes == 3


NUM_AGENTS_DICT = {
    5: [2, 3, 2, 3, 3],
    6: [2, 3, 4, 3, 4],
    7: [2, 3, 3, 4, 4],
    8: [3, 4, 4, 5, 5],
    9: [3, 4, 4, 5, 5],
    10: [3, 4, 4, 5, 5],
}
