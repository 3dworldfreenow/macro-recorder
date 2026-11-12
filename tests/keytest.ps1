# Test window: logs Right Arrow presses and mouse clicks (screen position)
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object Windows.Forms.Form
$f.Text = "KeyTest"; $f.Width = 420; $f.Height = 260; $f.KeyPreview = $true
$f.StartPosition = "Manual"; $f.Left = 590; $f.Top = 300
$lbl = New-Object Windows.Forms.Label
$lbl.Text = "Keys: 0  Clicks: 0"; $lbl.AutoSize = $true; $lbl.Top = 20; $lbl.Left = 20
$lbl.Font = New-Object Drawing.Font("Segoe UI", 14)
$f.Controls.Add($lbl)
$script:k = 0; $script:c = 0
$f.Add_KeyDown({ param($s, $e)
  Add-Content keytest_received.txt ("{0} {1}" -f $e.KeyCode, [DateTimeOffset]::Now.ToUnixTimeMilliseconds())
  if ($e.KeyCode -eq "Right") { $script:k++; $lbl.Text = "Keys: $script:k  Clicks: $script:c" }
})
$onClick = { param($s, $e)
  $p = [Windows.Forms.Cursor]::Position
  Add-Content keytest_received.txt ("Click {0} {1} {2}" -f [DateTimeOffset]::Now.ToUnixTimeMilliseconds(), $p.X, $p.Y)
  $script:c++; $lbl.Text = "Keys: $script:k  Clicks: $script:c"
}
$f.Add_MouseDown($onClick); $lbl.Add_MouseDown($onClick)
[void]$f.ShowDialog()
