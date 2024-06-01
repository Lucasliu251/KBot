import random

# 定义扑克牌
suits = ['Hearts', 'Diamonds', 'Clubs', 'Spades']
ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10, 'A': 11}

# 定义牌组
deck = [rank + ' of ' + suit for suit in suits for rank in ranks]

# 发牌函数
def deal_card(deck):
    card = random.choice(deck)
    deck.remove(card)
    return card

# 计算手牌的总分
def calculate_hand_value(hand):
    value = sum(values[card.split(' ')[0]] for card in hand)
    num_aces = sum(card.startswith('A') for card in hand)
    
    while value > 21 and num_aces:
        value -= 10
        num_aces -= 1
    
    return value

# 显示手牌
def show_hand(hand, hidden=False):
    if hidden:
        return '[Hidden], ' + ', '.join(hand[1:])
    return ', '.join(hand)

# 玩家类
class Player:
    def __init__(self, name):
        self.name = name
        self.hand = []
        self.balance = 1000
        self.bet = 0
    
    def reset_hand(self):
        self.hand = []
        self.bet = 0

# 初始化游戏
def initialize_game():
    num_players = int(input("Enter number of players (1-4): "))
    players = [Player(input(f"Enter name for player{i + 1}: ")) for i in range(num_players)]
    dealer = Player("Dealer")
    return players, dealer

# 玩家下注
def place_bets(players):
    for player in players:
        while True:
            bet = int(input(f"{player.name}, you have {player.balance} points. Enter your bet: "))
            if 0 < bet <= player.balance:
                player.bet = bet
                player.balance -= bet
                break
            else:
                print("Invalid bet amount.")

# 主游戏循环
def play_game():
    players, dealer = initialize_game()
    global deck
    while True:
        if len(deck) < 15:
            deck = [rank + ' of ' + suit for suit in suits for rank in ranks]
        
        for player in players:
            player.reset_hand()
        dealer.reset_hand()
        
        place_bets(players)
        
        # 发两张牌给每个玩家和庄家
        for _ in range(2):
            for player in players:
                player.hand.append(deal_card(deck))
            dealer.hand.append(deal_card(deck))
        
        # 显示初始手牌
        print(f"\nDealer's hand: {show_hand(dealer.hand, hidden=True)}")
        for player in players:
            print(f"{player.name}'s hand: {show_hand(player.hand)}")
        
        # 玩家回合
        for player in players:
            while True:
                if calculate_hand_value(player.hand) > 21:
                    print(f"{player.name} busts with {show_hand(player.hand)}")
                    break
                
                action = input(f"{player.name}, choose action: (h)it, (s)tand, (d)ouble down, s(p)lit: ").lower()
                
                if action == 'h':
                    player.hand.append(deal_card(deck))
                    print(f"{player.name}'s hand: {show_hand(player.hand)}")
                elif action == 's':
                    break
                elif action == 'd':
                    if player.balance >= player.bet:
                        player.balance -= player.bet
                        player.bet *= 2
                        player.hand.append(deal_card(deck))
                        print(f"{player.name}'s hand: {show_hand(player.hand)}")
                        break
                    else:
                        print("Not enough balance to double down.")
                elif action == 'p':
                    if len(player.hand) == 2 and player.hand[0].split(' ')[0] == player.hand[1].split(' ')[0]:
                        second_hand = [player.hand.pop()]
                        player.hand.append(deal_card(deck))
                        second_hand.append(deal_card(deck))
                        print(f"{player.name}'s first hand: {show_hand(player.hand)}")
                        print(f"{player.name}'s second hand: {show_hand(second_hand)}")
                        players.append(Player(f"{player.name} (Split Hand)"))
                        players[-1].hand = second_hand
                        players[-1].bet = player.bet
                        players[-1].balance = player.balance
                        break
                    else:
                        print("Cannot split this hand.")
        
        # 庄家回合
        print(f"\nDealer's hand: {show_hand(dealer.hand)}")
        while calculate_hand_value(dealer.hand) < 17:
            dealer.hand.append(deal_card(deck))
            print(f"Dealer's hand: {show_hand(dealer.hand)}")
        
        # 计算结果
        dealer_value = calculate_hand_value(dealer.hand)
        if dealer_value > 21:
            print(f"Dealer busts with {dealer_value}")
        
        for player in players:
            player_value = calculate_hand_value(player.hand)
            if player_value > 21:
                print(f"{player.name} busts and loses the bet of {player.bet} points.")
            elif dealer_value > 21 or player_value > dealer_value:
                winnings = player.bet * 2
                player.balance += winnings
                print(f"{player.name} wins with {player_value} and receives {winnings} points.")
            elif player_value == dealer_value:
                player.balance += player.bet
                print(f"{player.name} ties with {player_value} and gets back the bet of {player.bet} points.")
            else:
                print(f"{player.name} loses with {player_value} and loses the bet of {player.bet} points.")
        
        # 检查是否有玩家还要继续
        if not any(player.balance > 0 for player in players):
            print("All players are out of points. Game over.")
            break
        
        another_round = input("Do you want to play another round? (y/n): ").lower()
        if another_round != 'y':
            break

# 启动游戏
if __name__ == "__main__":
    play_game()
