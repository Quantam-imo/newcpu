import streamlit as st


st.title("Market Intelligence Dashboard")

phase = st.sidebar.selectbox("Phase", ["ACCUMULATION", "MANIPULATION", "EXPANSION"])
confidence = st.slider("Confidence", 0.0, 1.0, 0.7)

signal = "BUY" if confidence >= 0.6 else "WAIT"

col1, col2 = st.columns(2)
col1.metric("Signal", signal)
col2.metric("Confidence", f"{confidence:.2f}")

st.write(f"### Phase: {phase}")
st.write("### Trap: HIGH" if confidence > 0.75 else "### Trap: LOW")
st.write("### Behavior: TRAPPED" if confidence > 0.75 else "### Behavior: BALANCED")

if confidence > 0.7:
    st.success("Strong bullish setup detected")
else:
    st.warning("Low Confidence")