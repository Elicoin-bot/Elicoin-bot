import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class TicTacToeGame:
    def __init__(self, ai_starts=True, difficulty="medium"):
        self.board = [" "] * 9
        self.current_turn = "O" if ai_starts else "X"
        self.ai_starts = ai_starts
        self.difficulty = difficulty
        self.game_over = False

    def make_move(self, index, player):
        if self.board[index] == " " and not self.game_over and player == self.current_turn:
            self.board[index] = player
            self.current_turn = "O" if player == "X" else "X"
            return True
        return False

    def check_winner(self):
        winner = self.evaluate_winner()
        if winner in ["X", "O", "Draw"]:
            self.game_over = True
        return winner

    def evaluate_winner(self):
        b = self.board
        wins = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],
            [0, 3, 6], [1, 4, 7], [2, 5, 8],
            [0, 4, 8], [2, 4, 6]
        ]
        for i, j, k in wins:
            if b[i] == b[j] == b[k] and b[i] != " ":
                return b[i]
        if " " not in b:
            return "Draw"
        return None

    def ai_move(self):
        if self.current_turn != "O" or self.game_over:
            return

        if self.difficulty == "hard":
            if random.random() < 0.7:
                self.ai_move_strong()
            else:
                self.ai_move_random()
        else:  # medium
            if random.random() < 0.5:
                self.ai_move_strong()
            else:
                self.ai_move_random()

    def ai_move_random(self):
        available = [i for i, cell in enumerate(self.board) if cell == " "]
        if available:
            self.make_move(random.choice(available), "O")

    def ai_move_strong(self):
        best_score = -float("inf")
        best_move = None
        for i in range(9):
            if self.board[i] == " ":
                self.board[i] = "O"
                score = self.minimax(False)
                self.board[i] = " "
                if score > best_score:
                    best_score = score
                    best_move = i
        if best_move is not None:
            self.make_move(best_move, "O")

    def minimax(self, is_maximizing):
        winner = self.evaluate_winner()
        if winner == "O":
            return 1
        elif winner == "X":
            return -1
        elif winner == "Draw":
            return 0

        if is_maximizing:
            best = -float("inf")
            for i in range(9):
                if self.board[i] == " ":
                    self.board[i] = "O"
                    score = self.minimax(False)
                    self.board[i] = " "
                    best = max(score, best)
            return best
        else:
            best = float("inf")
            for i in range(9):
                if self.board[i] == " ":
                    self.board[i] = "X"
                    score = self.minimax(True)
                    self.board[i] = " "
                    best = min(score, best)
            return best

def draw_board(board):
    symbols = {"X": "❌", "O": "⭕", " ": "⬜"}
    rows = []
    for i in range(0, 9, 3):
        row = " ".join(symbols[board[j]] for j in range(i, i + 3))
        rows.append(row)
    return "\n".join(rows)

def build_game_keyboard(board):
    keyboard = []
    for i in range(0, 9, 3):
        row = [
            InlineKeyboardButton(
                board[j] if board[j] != " " else "⬜",
                callback_data=f"move_{j}"
            ) for j in range(i, i + 3)
        ]
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)




from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class PvPGameSession:
    def __init__(self, player1_id, player2_id):
        self.players = [player1_id, player2_id]
        self.board = [' '] * 9
        self.turn = 0  # 0 for player1, 1 for player2
        self.finished = False

    def current_player(self):
        return self.players[self.turn]

    def other_player(self):
        return self.players[1 - self.turn]

    def make_move(self, pos):
        if self.board[pos] == ' ':
            self.board[pos] = 'X' if self.turn == 0 else 'O'
            return True
        return False

    def check_win(self):
        b = self.board
        lines = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],  # rows
            [0, 3, 6], [1, 4, 7], [2, 5, 8],  # cols
            [0, 4, 8], [2, 4, 6]              # diagonals
        ]
        for i1, i2, i3 in lines:
            if b[i1] != ' ' and b[i1] == b[i2] == b[i3]:
                self.finished = True
                return True
        return False

    def is_draw(self):
        if ' ' not in self.board and not self.check_win():
            self.finished = True
            return True
        return False

    def get_board_text(self):
        symbols = {'X': '❌', 'O': '⭕', ' ': '⬜'}
        rows = []
        for i in range(0, 9, 3):
            row = [symbols[self.board[i]], symbols[self.board[i+1]], symbols[self.board[i+2]]]
            rows.append(''.join(row))
        return '\n'.join(rows)

    def get_inline_keyboard(self):
        keyboard = []
        for i in range(0, 9, 3):
            row = []
            for j in range(3):
                pos = i + j
                cell = self.board[pos]
                if cell == ' ':
                    row.append(InlineKeyboardButton("⬜", callback_data=f"pvp_move_{pos}"))
                else:
                    emoji = '❌' if cell == 'X' else '⭕'
                    row.append(InlineKeyboardButton(emoji, callback_data="disabled"))
            keyboard.append(row)
        return InlineKeyboardMarkup(keyboard)
