from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired

cl = Client()

def challenge_code_handler(username, choice):
    print(f"Instagram enviou um codigo de verificacao para {username}")
    print("Escolha do metodo:", choice)  # 0=email, 1=phone
    code = input("Digite o codigo recebido: ")
    return code

cl.challenge_code_handler = challenge_code_handler

try:
    result = cl.login('washingtonkirokiro', '123Mudar$$$')
    print('LOGIN OK')
    cl.dump_settings('session.json')
    print('Session salva em session.json')
except ChallengeRequired as e:
    print(f'Challenge required: {e}')
    # O handler acima deve ser chamado automaticamente
    # Mas se precisar manual:
    try:
        code = input("Digite o codigo de verificacao: ")
        cl.challenge_resolve(cl.last_json)
        print('Challenge resolvido!')
        cl.dump_settings('session.json')
    except Exception as e2:
        print(f'Falha ao resolver challenge: {e2}')
except Exception as e:
    print(f'ERROR: {type(e).__name__}: {e}')
