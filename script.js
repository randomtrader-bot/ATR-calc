function calculateTP() {
    const pair = document.getElementById("pair").value;
    const atr = parseFloat(document.getElementById("atr").value);
    const tpPercent = parseFloat(document.getElementById("tpPercent").value);

    if (isNaN(atr) || isNaN(tpPercent)) {
        alert("Please enter valid numbers for ATR and TP %");
        return;
    }

    const atrPips = atr * 10000;
    const tpPips = Math.round(atrPips * tpPercent * 10) / 10;

    document.getElementById("result").innerText = `${pair} TP: ${tpPips} pips`;
}
