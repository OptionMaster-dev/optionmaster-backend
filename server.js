const express = require("express");
const app = express();

// Status endpoint
app.get("/status", (req, res) => {
  res.json({
    status: "Backend is live",
    time: new Date().toISOString()
  });
});

// Default route
app.get("/", (req, res) => {
  res.send("OptionMaster Backend Running!");
});

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
