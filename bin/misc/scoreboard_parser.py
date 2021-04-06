#!/usr/bin/env python3

problems = 12
teams = 7

print('(')
print('"rows": [')

for i in range(teams):
    print('{')
    print(f'"team_id": "{i}",')
    print('"problems": [')

    for p in range(problems):
        print('{')

        time = input()
        if time != "":
            solved = 'true'
            time = int(time)
        else:
            solved = 'false'
        tries = input().split()
        if len(tries) == 0:
            num_judged = 0
        else:
            num_judged = int(tries[0])

        label = chr(ord('A') + p)
        print(f'"label": "{label}",')
        print(f'"num_judged": {num_judged},')
        if solved == "true":
            print(f'"solved": {solved},')
            print(f'"time": {time}')
        else:
            print(f'"solved": {solved}')

        if p < problems - 1:
            print('},')
        else:
            print('}')

    if i < teams - 1:
        print(']},')
        input()
    else:
        print(']}')

print("])")
