from game import Game

game = Game([], ("a", "b", "c", "d", "e", "f"))

game.make_roles()
assert len(game.spies) == 3

game.choose_mission_leader()
assert 0 <= game.mission_leader < len(game.players)

assert game.mission_size() == 2

assert not game.validate_mission(None)
assert not game.validate_mission("string")
assert not game.validate_mission(["a"])
assert not game.validate_mission(["a", "b", "c"])
assert not game.validate_mission(["a", "a"])
assert not game.validate_mission(["a", "g"])
assert game.validate_mission(["c", "d"])

for _ in range(20):
    game.update_mission_leader()
    assert 0 <= game.mission_leader < len(game.players)

assert game.mission_approved(6)
assert game.mission_approved(4)
assert not game.mission_approved(3)
assert not game.mission_approved(1)

assert game.mission_succeeds(0)
assert not game.mission_succeeds(1)

assert not game.game_over()
game.round_num = 2
assert game.game_over()
game.successes = 1
assert not game.game_over()
game.successes = 3
assert game.game_over()

assert game.resistance_won()
game.successes = 2
assert not game.resistance_won()
