from enum import Enum, auto


class GameStates(Enum):
    NOT_STARTED = auto()
    NOMINATING = auto()
    VOTING_MISSION = auto()
    RUNNING_MISSION = auto()
    GAME_OVER = auto()


class Game:
    def __init__(self, connections, players):
        self.connections = connections  # mutable reference outside of this scope.
        self.players = players  # should be immutable or owned by this class
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
        }

    async def player_move(self, player_id, move):
        handler = self.STATES[self.state]
        await handler(player_id, move)

    async def not_started(self, player_id, move):
        kind = move.get("kind")
        if kind == "start":
            await self.start()

    async def broadcast(self, message):
        for client, _ in self.connections:
            await client.put(message)

    def has_player(self, player_id):
        return player_id in self.players

    async def start(self):
        self.choose_mission_leader()
        self.make_roles()

        spy_message = {
            "kind": "game_start",
            "is_spy": True,
            "spies": list(self.spies),
            "players": self.players,
        }
        resistance_message = {
            "kind": "game_start",
            "is_spy": False,
            "players": self.players,
        }
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
                "mission_number": self.round_num + 1,
            }
        )
        await self.start_nomination()

    async def start_nomination(self):
        mission_leader = self.players[self.mission_leader]
        self.state = GameStates.NOMINATING
        await self.broadcast(
            {"kind": "nomination_start", "mission_leader": mission_leader,}
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
            }
        )
        if approved:
            self.state = GameStates.RUNNING_MISSION
            await self.start_mission()
        else:
            self.nominations_rejected += 1
            if self.nominations_rejected == 5:
                await self.broadcast(
                    {
                        "kind": "game_over",
                        "resistance_won": False,
                        "spies": list(self.spies),
                    }
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
                "mission_number": self.round_num + 1,
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

        # TODO (Elizabeth): determine the right number of spies for how many players there are
        num_spies = 0
        # TODO (Elizabeth): randomly select that many spies from our players
        self.spies = {"joseph"}

    def choose_mission_leader(self):
        """Randomly select a player to be the first mission leader."""
        num_players = len(self.players)
        # TODO (Elizabeth): choose a random number >= 0 and < num_players
        self.mission_leader = 0

    def mission_size(self):
        """Determine the number of people on the current mission."""
        num_players = len(self.players)
        # TODO (Elizabeth): Use num_players and self.round_num (where rounds are numbered 0-4, not 1-5)
        # TODO ------------ to figure out how many players are going on this mission and return it
        return 2

    def validate_mission(self, mission):
        """
        Check that a possible mission is valid.

        Specifically, it must:
          - have type list
          - have the length appropriate for the current mission size
          - have unique members who are all players of this game
        """
        # TODO (Elizabeth): write this function
        return True

    def update_mission_leader(self):
        """Update who the mission leader is."""
        num_players = len(self.players)
        # TODO (Elizabeth): Change self.mission_leader to be the next valid value (use %)
        self.mission_leader += 1

    def mission_approved(self, num_approve):
        """Check if a mission is approved."""
        num_players = len(self.players)
        # TODO (Elizabeth): Return True or False based on whether this mission has been approved
        return True

    def mission_succeeds(self, num_fails):
        """Check if a mission succeeds."""
        return num_fails < self.max_fails()

    def max_fails(self):
        """Get the maximum allowed number of fails for the current round."""
        num_players = len(self.players)
        # TODO (Elizabeth): Use self.round_num and num_players to determine the maximum number of fails allowed.
        # TODO -----------: This number is usually 0, except in large games in the fourth round.
        return 1

    def game_over(self):
        """Check if the game is over."""
        if self.round_num == 4:
            return True
        else:
            # TODO (Elizabeth): Use self.round_num and self.successes to determine if the game is over.
            return False

    def resistance_won(self):
        """Check if the resistance won. Assume the game is over."""
        # TODO (Elizabeth): Use self.successes to determine if the resistance won or not.
        return True
