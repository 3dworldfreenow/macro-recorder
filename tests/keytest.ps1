# Test window: counts Right Arrow presses it receives
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object Windows.Forms.Form
$f.Text = "KeyTest"; $f.Width = 420; $f.Height = 220; $f.KeyPreview = $true
$f.StartPosition = "Manual"; $f.Left = 40; $f.Top = 300
$lbl = New-Object Windows.Forms.Label
$lbl.Text = "Right arrows received: 0"; $lbl.AutoSize = $true; $lbl.Top = 60; $lbl.Left = 40
$lbl.Font = New-Object Drawing.Font("Segoe UI", 14)
$f.Controls.Add($lbl)
$script:n = 0
$f.Add_KeyDown({ param($s, $e)
  Add-Content keytest_received.txt ("{0} {1}" -f $e.KeyCode, [DateTimeOffset]::Now.ToUnixTimeMilliseconds())
  if ($e.KeyCode -eq "Right") { $script:n++; $lbl.Text = "Right arrows received: $script:n" }
})
[void]$f.ShowDialog()
