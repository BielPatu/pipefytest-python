
from flask import Flask, request, jsonify
import sqlite3
import os
import requests
from dotenv import load_dotenv

# =====================================
# CONFIGURAÇÕES
# =====================================

load_dotenv()

app = Flask(__name__)

DB = "restaurante.db"

PIPEFY_URL = "https://api.pipefy.com/graphql"
PIPEFY_TOKEN = os.getenv("PIPEFY_TOKEN")
PIPEFY_PIPE_ID = os.getenv("PIPEFY_PIPE_ID")


# =====================================
# CONEXÃO COM O BANCO
# =====================================

def conectar():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# =====================================
# CRIAR BANCO E ESTOQUE INICIAL
# =====================================


def verificar_baixo_estoque():

    LIMITE_ESTOQUE = 50

    conn = conectar()

    produtos = conn.execute("""
        SELECT nome, quantidade
        FROM estoque
        WHERE quantidade < ?
    """, (LIMITE_ESTOQUE,)).fetchall()

    conn.close()

    alertas = []

    for produto in produtos:

        try:

            card = criar_card_baixo_estoque(
                produto["nome"],
                produto["quantidade"]
            )

            alertas.append({
                "produto": produto["nome"],
                "quantidade": produto["quantidade"],
                "card_id": card["id"]
            })

        except Exception as erro:

            alertas.append({
                "produto": produto["nome"],
                "erro": str(erro)
            })

    return alertas





def enviar_graphql(mutation, variaveis):

    if not PIPEFY_TOKEN or not PIPEFY_PIPE_ID:
        raise ValueError("Token ou ID do Pipefy não configurado")

    resposta = requests.post(
        PIPEFY_URL,
        json={
            "query": mutation,
            "variables": variaveis
        },
        headers={
            "Authorization": f"Bearer {PIPEFY_TOKEN}",
            "Content-Type": "application/json"
        },
        timeout=20
    )

    resposta.raise_for_status()

    resultado = resposta.json()

    if resultado.get("errors"):
        raise Exception(str(resultado["errors"]))

    if not resultado.get("data"):
        raise Exception("Resposta inválida do Pipefy")

    return resultado





def criar_card_baixo_estoque(nome, quantidade):

    mutation = """
    mutation CriarAlerta($input: CreateCardInput!) {
        createCard(input: $input) {
            card {
                id
                title
            }
        }
    }
    """

    variaveis = {
        "input": {
            "pipe_id": int(PIPEFY_PIPE_ID),
            "phase_id": "344754865",

            "title": f"Baixo estoque - {nome}",

            "fields_attributes": [
                # Campo obrigatório do formulário inicial
                {
                    "field_id": "nome_do_produto",
                    "field_value": nome
                },

                # Campos da fase Estoque baixo
                {
                    "field_id": "nome",
                    "field_value": nome
                },
                {
                    "field_id": "prioridade",
                    "field_value": "318199545"
                },
                {
                    "field_id": "quantidade_de_itens_para_comprar",
                    "field_value": str(50 - quantidade)
                },
                {
                    "field_id": "respons_vel",
                    "field_value": "Gerente"
                }
            ]
        }
    }

    resultado = enviar_graphql(mutation, variaveis)

    card = resultado["data"]["createCard"]["card"]

    return {
        "id": card["id"],
        "titulo": card["title"]
    }



@app.route("/verificar-estoque", methods=["GET"])
def verificar_estoque():

    alertas = verificar_baixo_estoque()

    return jsonify({
        "mensagem": "Verificação de estoque concluída",
        "limite": 50,
        "alertas": alertas
    })




def inicializar_banco():

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            quantidade INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'solicitado',
            data TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS itens_compra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compra_id INTEGER NOT NULL,
            produto TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            FOREIGN KEY (compra_id) REFERENCES compras(id)
        )
    """)

    produtos = [
        ("Arroz", 20),
        ("Queijo", 10),
        ("Macarrão", 15)
    ]

    for nome, quantidade in produtos:
        cursor.execute("""
            INSERT OR IGNORE INTO estoque (nome, quantidade)
            VALUES (?, ?)
        """, (nome, quantidade))

    conn.commit()
    conn.close()


# =====================================
# INTEGRAÇÃO COM PIPEFY
# =====================================


def criar_card_pipefy(nome, quantidade, compra_id):

    if not PIPEFY_TOKEN or not PIPEFY_PIPE_ID:
        raise ValueError("Token ou ID do Pipefy não configurado")

    mutation = """
    mutation CriarCard($input: CreateCardInput!) {
        createCard(input: $input) {
            card {
                id
                title
            }
        }
    }
    """

    variaveis = {
        "input": {
            "pipe_id": int(PIPEFY_PIPE_ID),

            # Criar na fase Requisição
            "phase_id": "344755824",

            "title": f"Reposição de estoque - {nome}",

            "fields_attributes": [
                {
                    "field_id": "nome_1",
                    "field_value": nome
                },
                {
                    "field_id": "id_1",
                    "field_value": str(compra_id)
                },
                {
                    "field_id": "quantidade_de_itens_para_comprar_1",
                    "field_value": str(quantidade)
                }
            ]
        }
    }

    resposta = requests.post(
        PIPEFY_URL,
        json={
            "query": mutation,
            "variables": variaveis
        },
        headers={
            "Authorization": f"Bearer {PIPEFY_TOKEN}",
            "Content-Type": "application/json"
        },
        timeout=20
    )

    resposta.raise_for_status()

    resultado = resposta.json()

    if resultado.get("errors"):
        raise Exception(str(resultado["errors"]))

    card = resultado.get(
        "data", {}
    ).get(
        "createCard", {}
    ).get("card")

    if not card:
        raise Exception("Pipefy não retornou o card criado")

    return {
        "id": card["id"],
        "titulo": card["title"]
    }


# =====================================
# GET - CONSULTAR TODO O ESTOQUE
# =====================================

@app.route("/estoque", methods=["GET"])
def consultar_estoque():

    conn = conectar()

    produtos = conn.execute("""
        SELECT nome, quantidade
        FROM estoque
        ORDER BY id
    """).fetchall()

    conn.close()

    return jsonify([
        dict(produto) for produto in produtos
    ])


# =====================================
# GET - CONSULTAR UM PRODUTO
# =====================================

@app.route("/estoque/<nome>", methods=["GET"])
def consultar_produto(nome):

    conn = conectar()

    produto = conn.execute("""
        SELECT nome, quantidade
        FROM estoque
        WHERE nome = ? COLLATE NOCASE
    """, (nome,)).fetchone()

    conn.close()

    if produto is None:
        return jsonify({
            "erro": "Produto não encontrado"
        }), 404

    return jsonify(dict(produto))


# =====================================
# POST - CRIAR COMPRA E CARD NO PIPEFY
# =====================================

@app.route("/compras", methods=["POST"])
def criar_compra():

    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({
            "erro": "Envie um JSON válido"
        }), 400

    itens = dados.get("itens")

    if not isinstance(itens, list) or not itens:
        return jsonify({
            "erro": "Informe uma lista de itens"
        }), 400

    conn = conectar()

    try:

        itens_validos = []

        for item in itens:

            if not isinstance(item, dict):
                return jsonify({
                    "erro": "Item inválido"
                }), 400

            nome = item.get("nome")
            quantidade = item.get("quantidade")

            if not isinstance(nome, str) or not nome.strip():
                return jsonify({
                    "erro": "Nome inválido"
                }), 400

            nome = nome.strip()

            if (
                isinstance(quantidade, bool)
                or not isinstance(quantidade, int)
                or quantidade <= 0
            ):
                return jsonify({
                    "erro": "Quantidade deve ser um inteiro positivo"
                }), 400

            produto = conn.execute("""
                SELECT nome
                FROM estoque
                WHERE nome = ? COLLATE NOCASE
            """, (nome,)).fetchone()

            if produto is None:
                return jsonify({
                    "erro": f"Produto não cadastrado: {nome}"
                }), 400

            itens_validos.append((
                produto["nome"],
                quantidade
            ))

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO compras (status)
            VALUES ('solicitado')
        """)

        compra_id = cursor.lastrowid

        for nome, quantidade in itens_validos:

            cursor.execute("""
                INSERT INTO itens_compra
                (compra_id, produto, quantidade)
                VALUES (?, ?, ?)
            """, (compra_id, nome, quantidade))

        conn.commit()

        # Enviar os itens ao Pipefy

        cards_criados = []
        erros_pipefy = []

        for nome, quantidade in itens_validos:

            try:

                card = criar_card_pipefy(
                    nome,
                    quantidade,
                    compra_id
                )

                cards_criados.append({
                    "produto": nome,
                    "quantidade": quantidade,
                    "card_id": card["id"],
                    "titulo": card["titulo"]
                })

            except Exception as erro:

                erros_pipefy.append({
                    "produto": nome,
                    "erro": str(erro)
                })

        return jsonify({
            "mensagem": "Solicitação de compra criada!",
            "compra_id": compra_id,
            "status": "solicitado",

            "itens": [
                {
                    "nome": nome,
                    "quantidade": quantidade
                }
                for nome, quantidade in itens_validos
            ],

            "pipefy": {
                "cards_criados": cards_criados,
                "erros": erros_pipefy
            }

        }), 201

    except Exception:

        conn.rollback()

        return jsonify({
            "erro": "Erro ao criar compra"
        }), 500

    finally:
        conn.close()


# =====================================
# POST - COMPRAR INGREDIENTE ESPECÍFICO
# =====================================

@app.route("/comprar", methods=["POST"])
def comprar_ingrediente():

    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({
            "erro": "Envie um JSON válido"
        }), 400

    nome = dados.get("nome")
    quantidade = dados.get("quantidade")

    if not isinstance(nome, str) or not nome.strip():
        return jsonify({
            "erro": "Informe o nome do ingrediente"
        }), 400

    if (
        isinstance(quantidade, bool)
        or not isinstance(quantidade, int)
        or quantidade <= 0
    ):
        return jsonify({
            "erro": "A quantidade deve ser um número inteiro positivo"
        }), 400

    nome = nome.strip()

    conn = conectar()

    try:

        cursor = conn.cursor()

        ingrediente = cursor.execute("""
            SELECT nome, quantidade
            FROM estoque
            WHERE nome = ? COLLATE NOCASE
        """, (nome,)).fetchone()

        if ingrediente is None:
            return jsonify({
                "erro": "Ingrediente não encontrado no estoque"
            }), 404

        cursor.execute("""
            UPDATE estoque
            SET quantidade = quantidade + ?
            WHERE nome = ?
        """, (
            quantidade,
            ingrediente["nome"]
        ))

        novo_estoque = cursor.execute("""
            SELECT nome, quantidade
            FROM estoque
            WHERE nome = ?
        """, (ingrediente["nome"],)).fetchone()

        conn.commit()

        return jsonify({
            "mensagem": "Compra realizada com sucesso!",
            "ingrediente": novo_estoque["nome"],
            "quantidade_comprada": quantidade,
            "estoque_atual": novo_estoque["quantidade"]
        }), 200

    except Exception:

        conn.rollback()

        return jsonify({
            "erro": "Erro ao registrar compra"
        }), 500

    finally:
        conn.close()


# =====================================
# GET - LISTAR COMPRAS
# =====================================

@app.route("/compras", methods=["GET"])
def listar_compras():

    conn = conectar()

    compras = conn.execute("""
        SELECT * FROM compras
        ORDER BY id DESC
    """).fetchall()

    resultado = []

    for compra in compras:

        itens = conn.execute("""
            SELECT produto, quantidade
            FROM itens_compra
            WHERE compra_id = ?
        """, (compra["id"],)).fetchall()

        resultado.append({
            "id": compra["id"],
            "status": compra["status"],
            "data": compra["data"],
            "itens": [
                dict(item) for item in itens
            ]
        })

    conn.close()

    return jsonify(resultado)


# =====================================
# GET - CONSULTAR UMA COMPRA
# =====================================

@app.route("/compras/<int:compra_id>", methods=["GET"])
def consultar_compra(compra_id):

    conn = conectar()

    compra = conn.execute("""
        SELECT * FROM compras
        WHERE id = ?
    """, (compra_id,)).fetchone()

    if compra is None:
        conn.close()

        return jsonify({
            "erro": "Compra não encontrada"
        }), 404

    itens = conn.execute("""
        SELECT produto, quantidade
        FROM itens_compra
        WHERE compra_id = ?
    """, (compra_id,)).fetchall()

    resultado = {
        "id": compra["id"],
        "status": compra["status"],
        "data": compra["data"],
        "itens": [
            dict(item) for item in itens
        ]
    }

    conn.close()

    return jsonify(resultado)


# =====================================
# PATCH - ATUALIZAR STATUS DA COMPRA
# =====================================

@app.route("/compras/<int:compra_id>/status", methods=["PATCH"])
def atualizar_status(compra_id):

    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({
            "erro": "Envie um JSON válido"
        }), 400

    novo_status = dados.get("status")

    status_permitidos = [
        "a_caminho",
        "comprado"
    ]

    if novo_status not in status_permitidos:
        return jsonify({
            "erro": "Status permitido: a_caminho ou comprado"
        }), 400

    conn = conectar()

    try:

        cursor = conn.cursor()

        compra = cursor.execute("""
            SELECT status
            FROM compras
            WHERE id = ?
        """, (compra_id,)).fetchone()

        if compra is None:
            return jsonify({
                "erro": "Compra não encontrada"
            }), 404

        status_atual = compra["status"]

        if status_atual == "comprado":
            return jsonify({
                "erro": "Esta compra já foi concluída"
            }), 409

        if status_atual == "a_caminho" and novo_status == "a_caminho":
            return jsonify({
                "mensagem": "A compra já está a caminho"
            })

        if novo_status == "comprado":

            itens = cursor.execute("""
                SELECT produto, quantidade
                FROM itens_compra
                WHERE compra_id = ?
            """, (compra_id,)).fetchall()

            for item in itens:

                cursor.execute("""
                    UPDATE estoque
                    SET quantidade = quantidade + ?
                    WHERE nome = ?
                """, (
                    item["quantidade"],
                    item["produto"]
                ))

        cursor.execute("""
            UPDATE compras
            SET status = ?
            WHERE id = ?
        """, (
            novo_status,
            compra_id
        ))

        conn.commit()

        return jsonify({
            "mensagem": "Status atualizado com sucesso!",
            "compra_id": compra_id,
            "status": novo_status,
            "estoque_atualizado": novo_status == "comprado"
        })

    except Exception:

        conn.rollback()

        return jsonify({
            "erro": "Erro ao atualizar compra"
        }), 500

    finally:
        conn.close()


# =====================================
# INICIALIZAR SERVIDOR
# =====================================

inicializar_banco()

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
