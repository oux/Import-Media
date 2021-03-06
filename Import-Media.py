#!/usr/bin/python2.6

# dependences:
# imagemagick
# exif
# exiftran
# pmount

from __future__ import print_function
import pygtk
pygtk.require('2.0')
import gtk
from syslog import *
import curses
import os, re,subprocess, shutil
import filecmp
import dbus
import gobject
#Modules pour le multithreading
import thread,threading
import time

#Important : Initialisation pour l'utilisation de threads
gtk.gdk.threads_init()

debug = False

class DeviceAddedListener:
  """ Objet permettant de se mettre en ecoute de la detection d'un nouveau
  volume
  """
  def __init__(self,app):
    print('dbus init')
    self.bus = dbus.SystemBus()
    self.hal_manager_obj = self.bus.get_object(
                        "org.freedesktop.Hal",
                        "/org/freedesktop/Hal/Manager")
    self.hal_manager = dbus.Interface(self.hal_manager_obj,
                      "org.freedesktop.Hal.Manager")
    self.hal_manager.connect_to_signal("DeviceAdded", self._filter)
    self.app = app


  def _filter(self, udi):
    device_obj = self.bus.get_object ("org.freedesktop.Hal", udi)
    device = dbus.Interface(device_obj, "org.freedesktop.Hal.Device")

    if device.QueryCapability("volume"):
      return self.hook_volume(device)

  def hook_volume(self, volume):
    device_file = volume.GetProperty("block.device")
    label = volume.GetProperty("volume.label")
    fstype = volume.GetProperty("volume.fstype")
    mount_point = volume.GetProperty("volume.mount_point")
    mounted = volume.GetProperty("volume.is_mounted")
    try:
      size = volume.GetProperty("volume.size")
    except:
      size = 0
    print ("New storage device detected:")
    print ("  device_file: %s" % device_file)
    print ("  label: %s" % label)
    print ("  fstype: %s" % fstype)
    print ("  mount_point: %s" % mount_point)
    print ("  size: %s (%.2fGB)" % (size, float(size) / 1024**3))
    # TODO:msgbox pour confirmer si il faut faire quelque chose
    # self.app.mainlabel.set_text(device_file)
    t = threading.Thread(target=self.app.ImportMedia, args=(device_file,mount_point, mounted))
    t.start()

class exif():
  """ Objet permettant de gerer les tags exifs
  d'une image et de comparer deux images sur les criteres exifs:
    * comparaison plus rapide
    * Permet d'identifier deux images identiques meme si elle est tournee.
  """
  def __init__(self,name=None):
    self.attributs = dict()
    if name is not None:
      if os.path.isfile(name):
        ret = subprocess.Popen(["exif", name],env={"LC_ALL":"C" },stderr=subprocess.PIPE,stdout=subprocess.PIPE).communicate()[0]
        attrs = ret.splitlines()[4:]
        attrs = attrs[:-2]
        for attr in attrs:
          try:
            (key, value) = attr.split('|')
          except:
            continue
          if debug: print(key,value)
          self.attributs [ key.strip() ] = value.strip()

  def get(self,attr):
    try:
      return self.attributs[attr]
    except:
      return None

  def __eq__(self, other):
    ret = True
    for attr in self.attributs.keys():
      if attr not in [ 'Maker Note', 'Orientation', 'PixelXDimension', 'PixelYDimension' ]:
        pass
        if self.get(attr) != other.get(attr):
          ret = False
          break
    if ret:
      return True


class ihm_gtk():
  # encore necessaire ? :
  # align = gtk.Alignment()
  bars = list()

  def __init__(self):
    self.root = gtk.Window()
    # self.root = Window()
    self.root.connect("destroy", lambda w: gtk.main_quit())
    self.root.set_title("Import des photos")
    self.vbox = gtk.VBox(False, 2)
    self.vbox.set_border_width(10)
    self.root.add(self.vbox)
    self.vbox.show()

    # Create a centering alignment object
    self.align = gtk.Alignment(0.5, 0.5, 0, 0)
    self.vbox.pack_start(self.align, False, False, 5)
    self.align.show()

    self.mainlabel = gtk.Label('Importation des photos')
    self.mainlabel.set_justify(gtk.JUSTIFY_CENTER)
    # vbox.pack_start(self.mainlabel, False, False, 0)
    # self.align.add(self.mainlabel)
    self.vbox.pack_start(self.mainlabel, False, False, 1)
    self.mainlabel.show()

    # Bstart = gtk.Button("Start")
    # Bstart.connect("clicked", init_thread)
    # vbox.pack_start(Bstart, False, False, 0)
    # Bstart.show()

    self.root.show()

  def main(self):
    gtk.main()

  def bar(self):
    bar = gtk.ProgressBar()
    self.vbox.pack_start(bar, False, False, 1)
    bar.show()
    self.bars.append(bar)
    # return bars.index(bar)
    return bar

class ihm_cli():
  def __init__(self):
    print ("init_cli")

  class bar():
    def __init__(self):
      print ("init_cli_bar")

    def set_text():
      print ("init_cli_bar_set_text")

    def set_fraction():
      print ("init_cli_bar_set_fraction")

class ImportApp():
  directories = list()

  def __init__(self):
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)

    # Chargement du fichier de configuration
    try:
      execfile(os.path.expanduser("config.py"))
    except:
      try:
        execfile(os.path.expanduser("~/.import_photos_rc.py"))
      except:
        print('Erreur de chargement du fichier de configuration.')
        print('Creer un fichier ~/.import_photos_rc.py ou config.py contenant:')
        print('        # Pour activer l\'import des photos')
        print('        self.activeImportPhotos = True')
        print('        self.photosExtensions = (".jpg",".JPG",".jpeg",".JPEG")')
        print('        self.photosPathDest   = \'/home/users/maison/media/images/photos\'')
        print('        self.thumbnails_dir = \'PREVIEW\'')
        print('')
        print('        # Pour activer l\'import des videos')
        print('        self.activeImportVideos = True')
        print('        self.videosExtensions = (".avi",".3gp",".3GP",".AVI",".mpg",".MPG")')
        print('        self.videosPathDest   = \'/home/users/maison/media/images/photos\'')
        exit(1)

    # attente d'un chargement d'un nouveau volume a explorer
    self.WaitingForDevice()

  def WaitingForDevice(self):
    # self.mainlabel.set_text('waiting for device...')
    DeviceAddedListener(self)

  def ImportMedia(self,device_file, mount_point, mounted):
    if not mounted:
      print ("  not mounted ... mounting" )
      self.MountDevice(device_file)
    mount_point = "/media/%s" % os.path.basename(device_file)

    if self.activeImportPhotos: self.ImportPhotos(mount_point)
    if self.activeImportVideos: self.ImportVideos(mount_point)

    if not mounted:
      # une petite attente car si il n'y a rien a faire sur la partition elle
      # est busy au moment de la tentative de demontage.
      time.sleep(1)
      print ("Initially not mounted ... umounting" )
      self.UmountDevice(device_file)

  def ImportVideos(self,mount_point=None):
    # Create the ProgressBar
    bar = ihm.bar()
    videos = list()

    bar.set_text('Importation des videos de %s...' %
        os.path.basename(mount_point))
    # Recherche des fichiers video
    for source_dir in self.videosSources:
      path_source = '%s/%s' % (mount_point,source_dir)
      for rootpath, dirs, files in os.walk(path_source):
        for name in sorted(files):
          source = "%s/%s" % (rootpath, name)
          if os.path.splitext(source)[1] in self.videosExtensions:
            videos.append(source)

    # Traitement des fichiers videos
    compteur_files = 0
    date_pattern = re.compile(r'(\d+):(\d+):(\d+)')
    total_files  = len(videos)
    print("Nombre de fichier a traiter: %s" % total_files)

    if total_files == 0:
      bar.set_fraction(1)

    for source in videos:
      name = os.path.basename(source)
      act = False
      print(name, end=" :")
      compteur_files += 1
      if total_files != 0:
        bar.set_fraction(float(compteur_files) / total_files)
        bar.set_text('%s : %d/%d' %
            (os.path.basename(mount_point),compteur_files, total_files))
      if debug: print("%s ..." % source)
      rel_directory = time.strftime('%Y%m%d',
        time.localtime(os.path.getctime( source)))
      if rel_directory not in self.directories:
        self.directories.append(rel_directory)
      directory = "%s/%s" % (self.videosPathDest, rel_directory)
      destination_initiale = "%s/%s" % (directory, name)

      destination = destination_initiale
      compteur = 1
      must_copy = True

      # Creation du repertoire de destination avec le repertoire des images
      # redimensionnees
      if not os.path.isdir("%s/%s" % (directory, self.thumbnails_dir)):
        os.makedirs("%s/%s" % (directory, self.thumbnails_dir))

      # Recherche du nom de fichier de destination:
      #  * Pour eviter d'ecraser un fichier different mais de meme nom
      #  * Pour ne pas faire la copie si le fichier a deja ete transfere
      while os.path.isfile(destination):
        if debug: print("Fichier %s existant" % destination)
        if not os.path.getsize(source) == os.path.getsize(destination):
          if debug: print("Fichier %s different de la source" % destination)
          compteur += 1
          destination = re.sub(r'(\.[^\.]*)$',r'_%s\1' %
              compteur,destination_initiale)
        else:
          if debug: print("Fichier %s identique a la source" % destination)
          must_copy = False
          break

#        thumbnails = "%s/%s/%s" % (os.path.dirname(destination), self.thumbnails_dir, os.path.basename(destination))
#        # Faire la copie, la rotation et le redimensionnement si necessaire
      if must_copy:
        act = True
        syslog('%s => %s' % (source, destination))
        if debug: print(source, "=>", destination)
        print("Import", end=" ")
        shutil.copy(source, destination)
#        dest_exif = exif(destination)
#        if dest_exif.get('Orientation') != "top - left" and dest_exif.get('Orientation') != None:
#          act = True
#          syslog('Rotation: %s' % destination)
#          print("Rotation", end=" ")
#          subprocess.Popen(["exiftran", "-a", "-i", destination],stderr=subprocess.PIPE,stdout=subprocess.PIPE).communicate()
#        if not os.path.isfile(thumbnails):
#          act = True
#          syslog('Redimensionnement: %s' % thumbnails)
#          print("Redimensionnement", end=" ")
#          (stdoutdata, stderrdata) = subprocess.Popen(
#              ["convert", "-resize", "1024x1024", destination, thumbnails],stdin=subprocess.PIPE,stderr=subprocess.PIPE, stdout=subprocess.PIPE
#              ).communicate()

      if not act:
        syslog('%s = Rien a faire' % source)
        print("Rien a faire",end="")
      print()

    bar.set_text('Fin de l\'importation des videos de %s...' % os.path.basename(mount_point))

  def ImportPhotos(self,mount_point=None):
    # Create the ProgressBar
    bar = ihm.bar()
    photos = list()

    bar.set_text('Importation des photos de %s...' %
        os.path.basename(mount_point))
    for source_dir in self.photosSources:
      path_source = '%s/%s' % (mount_point,source_dir)
      for rootpath, dirs, files in os.walk(path_source):
        for name in sorted(files):
          if os.path.splitext(name)[1] in self.photosExtensions:
            photos.append("%s/%s" % (rootpath, name))

    # Recuperation des images
    compteur_files = 0
    total_files  = len(photos)
    date_pattern = re.compile(r'(\d+):(\d+):(\d+)')
    print("Nombre de fichier a traiter: %s" % total_files)

    if total_files == 0:
      bar.set_fraction(1)

    for source in photos:
      name = os.path.basename(source)
      act = False
      # Affichage du nom de fichier
      print(name, end=" :")
      compteur_files += 1
      if total_files != 0:
        bar.set_fraction(float(compteur_files) / total_files)
        bar.set_text('%s : %d/%d' %
            (os.path.basename(mount_point),compteur_files, total_files))
      if debug: print("%s ..." % source)
      source_exif = exif(source)
      try:
        rel_directory = date_pattern.sub(r'\1\2\3',
            source_exif.get('Date and Time').split()[0])
      except:
        try:
          rel_directory = date_pattern.sub(r'\1\2\3',
              source_exif.get('Date and Time (origi').split()[0])
        except:
          print()
          continue
      if rel_directory not in self.directories:
        self.directories.append(rel_directory)
      directory = "%s/%s" % (self.photosPathDest, rel_directory)
      destination_initiale = "%s/%s" % (directory, name)

      destination = destination_initiale
      compteur = 1
      must_copy = True

      # Creation du repertoire de destination avec le repertoire des images
      # redimensionnees
      if not os.path.isdir("%s/%s" % (directory, self.thumbnails_dir)):
        os.makedirs("%s/%s" % (directory, self.thumbnails_dir))

      # Recherche du nom de fichier de destination:
      #  * Pour eviter d'ecraser un fichier different mais de meme nom
      #  * Pour ne pas faire la copie si le fichier a deja ete transfere
      while os.path.isfile(destination):
        if debug: print("Fichier %s existant" % destination)
        if not source_exif == exif(destination):
          if debug: print("Fichier %s different de la source" % destination)
          compteur += 1
          destination = re.sub(r'(\.[^\.]*)$',r'_%s\1' %
              compteur,destination_initiale)
        else:
          if debug: print("Fichier %s identique a la source" % destination)
          must_copy = False
          break

      thumbnails = "%s/%s/%s" % (os.path.dirname(destination),
          self.thumbnails_dir, os.path.basename(destination))
      # Faire la copie, la rotation et le redimensionnement si necessaire
      if must_copy:
        act = True
        syslog('%s => %s' % (source, destination))
        if debug: print(source, "=>", destination)
        print("Import", end=" ")
        shutil.copy(source, destination)
      dest_exif = exif(destination)
      if dest_exif.get('Orientation') != "top - left" and dest_exif.get('Orientation') != None:
        act = True
        syslog('Rotation: %s' % destination)
        print("Rotation", end=" ")
        subprocess.Popen(["exiftran", "-a", "-i", destination],
            stderr=subprocess.PIPE,stdout=subprocess.PIPE).communicate()
      if self.thumbnails and not os.path.isfile(thumbnails):
        act = True
        syslog('Redimensionnement: %s' % thumbnails)
        print("Redimensionnement", end=" ")
        (stdoutdata, stderrdata) = subprocess.Popen(
            ["convert", "-resize", "%sx%s" % (thumbnails_size,thumbnails_size), destination, thumbnails],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
            stdout=subprocess.PIPE).communicate()
      if not act:
        syslog('%s = Rien a faire' % source)
        print("Rien a faire",end="")
      print()
    bar.set_text('Fin de l\'importation des photos de %s...' %
        os.path.basename(mount_point))

  def MountDevice(self,device_file):
    # self.mainlabel.set_text('Montage de %s' % device_file)
    ret = subprocess.Popen(["/usr/bin/pmount", device_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).communicate()[0]
    if ret is not None: print ('montage device %s %s' % (device_file,ret))

  def UmountDevice(self,device_file):
    # self.mainlabel.set_text('Demontage de %s' % device_file)
    ret = subprocess.Popen(["/usr/bin/pumount", device_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).communicate()[0]
    if ret is not None: print ('demontage device %s %s' % (device_file,ret))

if __name__ == "__main__":
  openlog('import_photos',LOG_INFO)
  try:
    ihm = ihm_gtk()
  except:
    ihm = ihm_cli()
  ImportApp()
  ihm.main()
  if debug: print('bye')
  closelog()

  # TODO:
  # Recuperation des videos:
  #  - parametrage des extensions (avi, 3gp, MTS)
  #  - classer dans les repertoires par date de creation de fichier.
  #  - dest parametrable et differentiable des images

  # Proposer une ihm permettant de saisir des commentaires pour l'integrer au nom du repertoire (date - commentaire)
  # Suppression de la source (avec verif d'integrite -probleme de comparaison apres rotation de l'image cf image magick-).
  # Message box pour confirmation d'import avant de comment.
  # S'inspirer du hotplug udev pour la version daemon : /etc/udev/hdparm.rules

  # Refs:
  # http://www.pygtk.org/pygtk2tutorial/sec-ProgressBars.html
  # http://majorsilence.com/pygtk_dbus_interprocess_communication

# vim: sw=2:tw=0:ts=2
