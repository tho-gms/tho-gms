# whoop-mcp

Servidor MCP que calcula o teu défice calórico diário: o que gastas (WHOOP) menos o que comes (registo local).

A WHOOP não tem dados de nutrição na API. A comida fica numa base de dados SQLite no teu computador. Basta dizer ao Claude o que comeste ("almocei um prato de frango com arroz e salada"); ele estima as calorias e regista.

## Usar no telemóvel

A app Claude no telemóvel liga-se a servidores MCP pela internet, por isso o servidor tem de estar online. Estas instruções usam o [Railway](https://railway.com) (plano Hobby, cerca de 5 $/mês), porque tem disco persistente e faz-se tudo no browser do telemóvel. O Dockerfile funciona em qualquer outro serviço que tenha disco persistente.

Precisas de três coisas: o servidor no Railway, uma app no painel de programador da WHOOP e o conector no Claude.

### 1. Pôr o servidor online (Railway)

1. Entra em railway.com com a tua conta GitHub.
2. **New Project → Deploy from GitHub repo →** escolhe `tho-gms/tho-gms`.
3. No serviço criado, em **Settings**:
   - **Source → Root Directory:** `whoop-mcp`
   - **Source → Branch:** o ramo onde está este código (ou `main`, depois de o juntares)
   - **Networking → Generate Domain.** Fica com um endereço tipo `whoop-mcp-production.up.railway.app`. Guarda-o.
4. Adiciona um volume ao serviço (no projeto: **Create → Volume**) com mount path `/data`. É aqui que ficam os tokens da WHOOP e o teu registo de comida. Sem o volume, perdes tudo a cada atualização.

### 2. Criar a app na WHOOP

1. Entra em developer-dashboard.whoop.com com a tua conta WHOOP.
2. Cria uma app com os scopes `read:profile`, `read:body_measurement`, `read:cycles`, `read:recovery`, `read:sleep`, `read:workout` e `offline`.
3. Redirect URI: `https://O-TEU-DOMINIO/whoop/callback` (o domínio do passo 1).
4. Copia o Client ID e o Client Secret.

### 3. Variáveis no Railway

Em **Variables**, adiciona:

| Variável | Valor |
|---|---|
| `WHOOP_CLIENT_ID` | da WHOOP |
| `WHOOP_CLIENT_SECRET` | da WHOOP |
| `ACCESS_KEY` | uma chave aleatória com 32+ letras e números, sem símbolos. Usa o gerador de palavras-passe do telemóvel. |

O Railway reinicia o servidor sozinho. O endereço público é detetado pela variável `RAILWAY_PUBLIC_DOMAIN`, que o Railway já define. Noutro serviço, define `PUBLIC_URL=https://o-teu-dominio`. O fuso horário é `Europe/Lisbon` por omissão; muda com `TIMEZONE`.

### 4. Ligar ao Claude

1. No browser, abre https://claude.ai/customize/connectors.
2. **Add custom connector.** Nome: `WHOOP`. URL: `https://O-TEU-DOMINIO/A-TUA-ACCESS_KEY/mcp`
3. O conector aparece também na app do telemóvel.

A `ACCESS_KEY` no URL é a única proteção do servidor. Quem tiver o URL completo vê e altera os teus dados. Não o partilhes. Se o perderes, muda a `ACCESS_KEY` no Railway e atualiza o conector.

### 5. Primeira conversa no telemóvel

> Liga a minha WHOOP.

O Claude dá-te um link. Abres, fazes login na WHOOP, aceitas, e está feito. Depois:

> Configura o meu perfil: homem, nascido a 1999-05-14, trabalho de secretária, quero um défice de 500 kcal.

## Como calcula

**Gasto.** Para um dia completo, o gasto é o `kilojoule` do ciclo da WHOOP convertido em kcal. Esse valor já inclui o metabolismo basal, o trabalho e os treinos. Tem três ajustes:

- O dia de hoje ainda não acabou. O ciclo atual só tem o gasto até agora. O servidor projeta o fim do dia somando BMR × nível de atividade do trabalho pelas horas que faltam.
- Sem dados da WHOOP (pulseira fora, a carregar), usa a fórmula: BMR (Mifflin-St Jeor) × nível de atividade do trabalho + treinos.
- A WHOOP pode sobrestimar ou subestimar. `expenditure_correction_pct` corrige isso, e `calibrate_metabolism` calcula o valor certo a partir do teu peso real.

**Défice** = gasto − ingestão. Positivo é défice.

**Calibração.** Com 2 a 4 semanas de comida registada e várias pesagens, o servidor calcula quanto gastas de facto: ingestão média − (variação de peso por dia × 7700 kcal/kg). Compara com a média da WHOOP e sugere a correção.

**Trabalho.** O nível de atividade do trabalho (`job_activity`) não inclui ginásio nem desporto, porque a WHOOP conta os treinos à parte:

| Valor | Fator | Exemplo |
|---|---|---|
| `sedentary` | 1.2 | secretária, pouco andar |
| `light` | 1.375 | de pé parte do dia |
| `moderate` | 1.55 | a andar quase o dia todo |
| `heavy` | 1.725 | trabalho físico |

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| `whoop_connect_link` | Link para ligar (ou voltar a ligar) a conta WHOOP |
| `whoop_status` | Testa a ligação e mostra perfil e medidas da WHOOP |
| `set_profile` | Sexo, data de nascimento, altura, trabalho, meta de défice, correção |
| `log_food` / `get_food_log` / `delete_food` | Registo de comida (kcal e macros) |
| `log_weight` / `get_weight_trend` | Pesagens e tendência em kg/semana |
| `get_energy_balance` | Balanço de um dia: ingestão, gasto, défice, kcal que ainda podes comer, macros, proteína por kg, treinos, strain, recuperação, sono |
| `get_deficit_summary` | Vários dias: défice por dia, totais, médias, perda de gordura esperada e tendência real do peso |
| `calibrate_metabolism` | Compara a WHOOP com o teu peso real e sugere (ou aplica) a correção |

## Instalação no computador

Alternativa ao telemóvel: corre no teu computador e liga-se ao Claude Code ou ao Claude Desktop.

### 1. Criar uma app na WHOOP

1. Entra em https://developer-dashboard.whoop.com com a tua conta WHOOP.
2. Cria uma app com todos os scopes de leitura (`read:profile`, `read:body_measurement`, `read:cycles`, `read:recovery`, `read:sleep`, `read:workout`) e `offline`.
3. Adiciona o redirect URI `http://localhost:8765/callback`.
4. Copia o Client ID e o Client Secret.

### 2. Instalar

```bash
cd whoop-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Credenciais

```bash
mkdir -p ~/.whoop-mcp
cp .env.example ~/.whoop-mcp/.env
# edita ~/.whoop-mcp/.env com o Client ID e o Client Secret
```

### 4. Autorizar

```bash
whoop-mcp auth
```

Abre o browser, aceitas, e os tokens ficam em `~/.whoop-mcp/tokens.json`. O servidor renova-os sozinho.

### 5. Ligar ao Claude

**Claude Code:**

```bash
claude mcp add whoop -- /caminho/para/whoop-mcp/.venv/bin/whoop-mcp serve
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "whoop": {
      "command": "/caminho/para/whoop-mcp/.venv/bin/whoop-mcp",
      "args": ["serve"]
    }
  }
}
```

## Exemplos

No dia a dia:

> Ao pequeno-almoço comi duas torradas com manteiga e um galão.
> Qual é o meu défice hoje? Quanto posso ainda comer ao jantar?
> Pesei 78,4 kg esta manhã.
> Resume a última semana.

Ao fim de 3 semanas:

> Calibra o metabolismo com os últimos 21 dias.

## Limitações

- A precisão depende do registo de comida. Um dia sem tudo registado parece um défice que não existiu.
- As estimativas de calorias da WHOOP (e de qualquer wearable) têm erro. Por isso existe a calibração.
- O peso varia 1 a 2 kg por dia com água, sal e hidratos. A calibração precisa de várias semanas.
- Os caminhos da API estão em `src/whoop_mcp/config.py`. Se a WHOOP mudar um endpoint, corrige-se aí.

## Testes

```bash
pip install -e ".[dev]"
pytest
```
